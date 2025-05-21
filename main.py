import os
from dotenv import load_dotenv
from pathlib import Path
import argparse

from scripts.generate_insights import PromptRenderer
from scripts.api_calls import generate_response
import scripts.constants as const
from scripts.utils import extract_asset_quality_metrics, load_pmi_time_series, load_ifo_data, extract_metrics_from_excel, read_text_file

load_dotenv()

def parse_args():
    parser = argparse.ArgumentParser(description="Run KPI prompt generation")
    parser.add_argument(
        "--segment",
        choices=["FinSum", "IB", "PB", "CB"],
        default="FinSum",
        required=True,
        help="Select a bank segment"
    )
    parser.add_argument(
        "--macro_kpis",
        choices=["ifo", "pmi"],
        nargs="+",
        default=["ifo"],
        required=True,
        help="Select one or more macroeconomic indicators to include (e.g., --macro_kpis ifo pmi)"
    )
    parser.add_argument(
        "--user_comments",
        type=str,
        required=False,
        help="Insert additional user comments to enrich the analysis"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    segment = const.SEGMENTS[args.segment]
    macro_kpis = args.macro_kpis
    user_comments = args.user_comments or ""

    # Load Data
    df_ifo = load_ifo_data(csv_path=os.path.join(const.PROJECT_ROOT, "data", "202504_ifo_gsk_prepared.csv"), start_date="2020-01-01") if "ifo" in macro_kpis else None
    pmi_pdf_path = os.path.join(const.PROJECT_ROOT, "data", "202502_pmi.pdf") if "pmi" in macro_kpis else None
    df_pmi_ts = load_pmi_time_series(os.path.join(const.PROJECT_ROOT, "data", "global_composite_pmi.csv")) if "pmi" in macro_kpis else None
    bank_data_all_dict = extract_metrics_from_excel(os.path.join(const.PROJECT_ROOT, "data", "FDS-Q4-2024-13032025.xlsb"))
    bank_data_dict = bank_data_all_dict.get(segment, {})
    df_gross_carrying_amount, df_allowance_for_credit_losses = extract_asset_quality_metrics(os.path.join(const.PROJECT_ROOT, "data", "FDS-Q4-2024-13032025.xlsb")) if segment == "total_bank" else (None, None)
    example = read_text_file(os.path.join(const.PROJECT_ROOT, "data", "examples.txt"))


    # Prepare context
    context = {
        "segment": segment,
        "domain": "Banking",
        "product_type": "Loans",
        "bank_data": bank_data_dict,
        "gross_carrying_amount" : df_gross_carrying_amount,
        "allowance_for_credit_losses" : df_allowance_for_credit_losses,
        "ifo_data": df_ifo.to_string(index=True) if df_ifo is not None else None,
        "pmi_data": "Please find the PMI data in the PDF report." if pmi_pdf_path is not None else None,
        "pmi_time_series" : df_pmi_ts,
        "user_comments": user_comments,
        "example": example
    }

    # Generate response
    renderer = PromptRenderer(template_dir=Path("prompts"))
    prompt = renderer.render_instruction_prompt(context)

    print("\n--- PROMPT ---\n")
    print(prompt)

    response = generate_response(prompt, pmi_pdf_path)

    print("\n--- RESPONSE ---\n")
    print(response)