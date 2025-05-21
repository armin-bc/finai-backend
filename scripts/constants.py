import os

# Folders
FILE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(FILE_DIR)

# Model
MODEL = "gemini-2.5-flash-preview-04-17"
MAX_RETRIES = 5
RETRY_DELAY = 3

# KPI Lables and Segments
KPI_LABELS = {
    "provision_for_credit_losses_bps_avg_loans": [
        "provision for credit losses",
        "credit losses",
        "llp",
        "pcl",
        "bps",
        "basispunkte",
    ],
    "allowance_for_loan_losses_in_eur_bn": ["allowance for loan losses"],
    "average_loans_gross_of_allowance_for_loan_losses_in_eur_bn": [
        "average loans (gross of allowance for loan losses)"
    ],
    "loans_gross_of_allowance_for_loan_losses_in_eur_bn": [
        "loans (gross of allowance for loan losses)"
    ],
}

# Sheet names mapped to business segments
SEGMENTS = {
    "FinSum": "total_bank",
    "CB": "corporate_bank",
    "IB": "investment_bank",
    "PB": "private_bank",
}
