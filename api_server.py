import logging

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
import subprocess
import json
import os
import sys
from pathlib import Path
import pandas as pd
import fitz  # Für PDFs
from docx import Document  # Für Word
import openpyxl  # Für Excel

# Import from your existing backend
from scripts.generate_insights import PromptRenderer
from scripts.api_calls import generate_response
import scripts.constants as const
from scripts.utils import load_ifo_data, extract_metrics_from_excel, read_text_file
from scripts.utils import prepare_chart_data
from scripts.utils import (
    extract_text_from_pdf,
    extract_text_from_docx,
    extract_text_from_excel,
)

app = Flask(__name__)

CORS(
    app,
    resources={r"/api/*": {"origins": "https://armin-bc.github.io"}},
    supports_credentials=True,
)

# Increase max content length for file uploads
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB


# Add a test endpoint to verify CORS is working
@app.route("/api/cors-test", methods=["GET", "OPTIONS"])
def cors_test():
    response = jsonify({"message": "CORS test successful", "status": "ok"})
    return response


@app.route("/")
def api_root():
    return jsonify(
        {
            "message": "FinAI Backend API",
            "status": "running",
            "endpoints": ["/api/cors-test", "/api/upload", "/api/analyze"],
        }
    )


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Main endpoint to process data from the frontend tool and return analysis"""
    try:
        data = request.json
        segment = data.get("segment", "FinSum")  # Default to FinSum if not provided

        # Map frontend segment names to backend segment codes
        segment_mapping = {
            "Retail": "PB",  # Assuming Retail maps to Private Bank
            "Corporate": "CB",
            "Investment": "IB",
            "Total": "FinSum",
        }

        # Convert frontend segment name to backend segment code
        segment_code = segment_mapping.get(segment, "FinSum")

        # Get selected KPIs and convert to macro_kpis format
        selected_kpis = data.get("kpis", [])

        macro_kpis = []
        include_ifo = False
        include_pmi = False

        if "Ifo" in selected_kpis:
            macro_kpis.append("ifo")
            include_ifo = True
        if "PMI" in selected_kpis:
            macro_kpis.append("pmi")
            include_pmi = True

        # Get user comments
        user_comments = data.get("comments", "")

        # Process uploaded files
        main_documents = data.get("mainDocuments", [])
        additional_documents = data.get("additionalDocuments", [])

        uploaded_texts = []
        all_filenames = main_documents + additional_documents

        for filename in all_filenames:
            if not filename or not isinstance(filename, str):
                continue
            path = os.path.join(const.PROJECT_ROOT, "uploads", filename)
            if os.path.exists(path):
                try:
                    if filename.endswith((".txt", ".csv")):
                        with open(path, "r", encoding="utf-8") as f:
                            content = f.read()

                    elif filename.endswith(".pdf"):
                        content = extract_text_from_pdf(path)

                    elif filename.endswith(".docx"):
                        content = extract_text_from_docx(path)

                    elif filename.endswith(".xlsx"):
                        content = extract_text_from_excel(path)

                    else:
                        content = f"[Dateityp {filename} wird nicht unterstützt]"

                    uploaded_texts.append(
                        f"Inhalt von {filename}:\n{content[:3000]}"
                    )  # Zeichenlimit pro Datei

                    print(f"Erkannte Datei: {filename}, Textbeginn: {content[:100]}")

                except Exception as e:
                    print(f"Fehler beim Lesen von {filename}: {e}")

        # Load data based on selection
        segment_name = const.SEGMENTS[segment_code]

        # Load IFO data if needed
        df_ifo = None
        if "ifo" in macro_kpis:
            try:
                ifo_path = os.path.join(
                    const.PROJECT_ROOT, "data", "202504_ifo_gsk_prepared.csv"
                )
                df_ifo = load_ifo_data(ifo_path)
            except Exception as e:
                print(f"Error loading IFO data: {e}")
                pass  # Continue without IFO data if loading fails

        # Load PMI data if needed
        df_pmi = None
        if "pmi" in macro_kpis:
            try:
                pmi_path = os.path.join(
                    const.PROJECT_ROOT, "data", "global_composite_pmi.csv"
                )
                df_pmi = pd.read_csv(pmi_path)

                # Process month strings to dates
                # Assuming month column is in format like "Jan 2023"
                df_pmi["Date"] = pd.to_datetime(df_pmi["Month"], format="%m/%Y")
                df_pmi.set_index("Date", inplace=True)

            except Exception as e:
                print(f"Error loading PMI data: {e}")
                # Continue without PMI data if loading fails

        # Set PMI path if needed
        pmi_pdf_path = None
        if "pmi" in macro_kpis:
            pmi_pdf_path = os.path.join(const.PROJECT_ROOT, "data", "202502_pmi.pdf")

        # Load bank data
        try:
            excel_path = os.path.join(
                const.PROJECT_ROOT, "data", "FDS-Q4-2024-13032025.xlsb"
            )
            bank_data_all_dict = extract_metrics_from_excel(excel_path)

            # Set default if segment not found
            if segment_name not in bank_data_all_dict:
                bank_data_dict = {}
            else:
                bank_data_dict = bank_data_all_dict[segment_name]
        except Exception as e:
            print(f"Error extracting bank data: {e}")
            bank_data_all_dict = {}
            bank_data_dict = {}

        try:
            example = read_text_file(
                os.path.join(const.PROJECT_ROOT, "data", "examples.txt")
            )
        except Exception as e:
            print(f"Error reading example text: {e}")
            example = ""

        # Prepare context
        context = {
            "segment": segment_name,
            "domain": "Banking",
            "product_type": "Loans",
            "bank_data": bank_data_dict,
            "ifo_data": df_ifo.to_string(index=True) if df_ifo is not None else None,
            "pmi_data": (
                "Please find the PMI data in the PDF report."
                if pmi_pdf_path is not None
                else None
            ),
            "user_comments": user_comments,
            "example": example,
            "uploaded_documents_text": "\n\n".join(uploaded_texts),
        }

        # Zusätzliche KPIs explizit für den Prompt verfügbar machen
        context["gross_carrying_amount"] = bank_data_dict.get(
            "gross_carrying_amount_in_eur_bn", {}
        )
        context["allowance_for_credit_losses"] = bank_data_dict.get(
            "allowance_for_loan_losses_in_eur_bn", {}
        )

        context["uploaded_documents_text"] = "\n\n".join(uploaded_texts)

        # Generate response
        try:
            renderer = PromptRenderer(template_dir=Path("prompts"))
            prompt = renderer.render_instruction_prompt(context)
            print("\n--- FINALER PROMPT ---")
            print(prompt)
            ai_response = generate_response(prompt, pmi_pdf_path)
        except Exception as e:
            ai_response = f"Error generating analysis: {str(e)}"

        # Generate chart data for provision_for_credit_losses_bps_avg_loans
        try:
            chart_data = prepare_chart_data(
                bank_data_all_dict,
                segment_name,
                "provision_for_credit_losses_bps_avg_loans",
                df_ifo=df_ifo,
                include_ifo=include_ifo,
            )
        except Exception as e:
            print(f"Error preparing IFO chart: {e}")
            # Provide a minimal fallback chart structure
            chart_data = {
                "labels": [],
                "datasets": [
                    {
                        "label": "Provision for Credit Losses (bps of Avg Loans)",
                        "data": [],
                        "borderColor": "#4285F4",
                        "backgroundColor": "rgba(66, 133, 244, 0.2)",
                    }
                ],
            }

        # Prepare PMI chart data with the same time periods as the main chart
        pmi_chart_data = None
        if include_pmi and df_pmi is not None:
            try:
                # Use the same periods from the main chart
                periods = chart_data.get("labels", [])

                # Create PMI chart dataset
                pmi_values = []

                for period in periods:
                    try:
                        period_str = str(period).strip().upper()

                        # Extract year and quarter
                        if "FY" in period_str:
                            # Handle fiscal year format
                            year_str = (
                                period_str.replace("FY", "").replace("_", "").strip()
                            )
                            year = int(year_str)

                            # Get average PMI value for the year
                            yearly_pmi = df_pmi[df_pmi.index.year == year][
                                "Composite_PMI"
                            ].mean()
                            pmi_values.append(
                                float(yearly_pmi) if not pd.isna(yearly_pmi) else None
                            )

                        elif "Q" in period_str:
                            # Handle quarterly format
                            if "_" in period_str:
                                parts = period_str.split("_")
                                quarter_part = parts[0] if len(parts) > 0 else ""
                                year_part = parts[1] if len(parts) > 1 else ""
                            else:
                                # Extract using character types
                                quarter_part = "".join(
                                    [
                                        c
                                        for c in period_str
                                        if c.isalpha() or c.isspace()
                                    ]
                                )
                                year_part = "".join(
                                    [c for c in period_str if c.isdigit()]
                                )

                            quarter = int(quarter_part.replace("Q", ""))
                            year = int(year_part)

                            # Calculate months for this quarter
                            start_month = (quarter - 1) * 3 + 1
                            end_month = quarter * 3

                            # Filter PMI data for this quarter
                            quarter_pmi = df_pmi[
                                (df_pmi.index.year == year)
                                & (df_pmi.index.month >= start_month)
                                & (df_pmi.index.month <= end_month)
                            ]["Composite_PMI"].mean()

                            pmi_values.append(
                                float(quarter_pmi) if not pd.isna(quarter_pmi) else None
                            )
                        else:
                            pmi_values.append(None)

                    except Exception as e:
                        print(f"Error processing PMI value for period {period}: {e}")
                        pmi_values.append(None)

                # Create PMI chart data structure
                pmi_chart_data = {
                    "labels": periods,
                    "datasets": [
                        {
                            "label": "Provision for Credit Losses (bps of Avg Loans)",
                            "data": chart_data["datasets"][0][
                                "data"
                            ],  # kopiere aus Hauptchart
                            "borderColor": "#4285F4",
                            "backgroundColor": "rgba(66, 133, 244, 0.2)",
                        },
                        {
                            "label": "Global Composite PMI",
                            "data": pmi_values,
                            "borderColor": "#EA4335",
                            "backgroundColor": "rgba(234, 67, 53, 0.2)",
                            "yAxisID": "y1",
                        },
                    ],
                }

            except Exception as e:
                print(f"Error preparing PMI chart: {e}")
                pmi_chart_data = None

        # Process the response into an easy-to-use format for the frontend
        analysis_result = {
            "variance_analysis": {"title": "Variance Analysis", "content": ai_response},
            "trend_analysis": {
                "title": "Trend Analysis",
                "summary": "The AI has analyzed trends based on the provided data and macro indicators.",
            },
            "chart": chart_data,  # IFO and PCL chart data
            "pmi_chart": pmi_chart_data,  # Add PMI chart data to the response
            "ifo_chart": include_ifo,  # Flag to indicate IFO was selected
            "pmi_chart_selected": include_pmi,  # Flag to indicate PMI was selected
        }

        response = jsonify(
            {
                "success": True,
                "message": "Analysis completed successfully",
                "result": analysis_result,
            }
        )
        return response

    except Exception as e:
        import traceback

        error_traceback = traceback.format_exc()
        print("❌ Fehler im /api/analyze-Endpunkt:")
        print(error_traceback)

        response = jsonify(
            {
                "success": False,
                "message": f"Error processing request: {str(e)}",
                "traceback": error_traceback,
            }
        )
        return response, 500


@app.route("/api/upload", methods=["POST", "OPTIONS"])
def upload_file():
    """Endpoint to handle file uploads"""

    try:
        if "file" not in request.files:
            response = jsonify({"success": False, "message": "No file part"})
            return response, 400

        file = request.files["file"]
        if file.filename == "":
            response = jsonify({"success": False, "message": "No selected file"})
            return response, 400

        # Create upload directory if it doesn't exist
        upload_dir = os.path.join(const.PROJECT_ROOT, "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        # Save the file
        file_path = os.path.join(upload_dir, file.filename)
        file.save(file_path)

        response = jsonify(
            {
                "success": True,
                "message": "File uploaded successfully",
                "filename": file.filename,
                "path": file_path,
            }
        )
        return response

    except Exception as e:
        response = jsonify(
            {"success": False, "message": f"Error uploading file: {str(e)}"}
        )
        return response, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
