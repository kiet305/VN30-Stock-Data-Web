import re
import unicodedata

import pandas as pd
from dagster import AllPartitionMapping, AssetIn, Output, asset
from etl_pipeline.assets.bronze.reports import report_partitions

GOLD_REPORT_COLUMNS = [
    "ticker",
    "industry",
    "subindustry",
    "industry_group",
    "year",
    "quarter",
    "period_label",
    "report_type",
    "statement_type",
    "report_name",
    "item_code",
    "parent_item_code",
    "line_item_key",
    "parent_line_item_key",
    "criteria",
    "standard_name",
    "level_1",
    "level_2",
    "level_3",
    "item_id",
    "item_name_vi",
    "item_name_en",
    "display_label",
    "line_no",
    "line_index",
    "parent_line_index",
    "hierarchy_depth",
    "hierarchy_path",
    "classification_path",
    "children_count",
    "child_item_codes",
    "has_children",
    "is_expandable",
    "default_expanded",
    "visible_by_default",
    "calculation_formula",
    "value",
    "display_order",
    "level",
    "is_total",
    "is_leaf",
    "sign_rule",
    "mapping_source",
    "unit",
]

FINANCIAL_REPORT_GROUPS = {"bank", "securities", "insurance", "financial_services"}

REPORT_LEVELS = {
    "BS": {
        "bank": [
            ("asset_liquidity", "Tài sản", "Tiền và thanh khoản", (
                "tien mat", "tien gui tai ngan hang nha nuoc", "ngan hang nha nuoc",
                "sbv", "tctd khac", "credit institutions", "cash",
            )),
            ("asset_earning", "Tài sản", "Tài sản sinh lãi", (
                "cho vay khach hang", "loans to customers", "chung khoan",
                "securities", "dau tu", "investment", "gop von", "mua co phan",
            )),
            ("asset_other", "Tài sản", "Tài sản khác", (
                "tai san co dinh", "fixed assets", "bat dong san", "du phong",
                "tai san khac", "other assets", "thue", "tax", "lai phi phai thu",
            )),
            ("liability_funding", "Nợ phải trả", "Nguồn vốn huy động", (
                "no chinh phu", "nhnn", "tien gui", "vay cac tctd", "khach hang",
                "phat hanh giay to", "deposits", "borrowings", "valuable papers",
            )),
            ("liability_other", "Nợ phải trả", "Nghĩa vụ khác", (
                "no phai tra", "phai tra", "cong cu tai chinh", "phai sinh",
                "uy thac", "tai tro", "thue", "du phong", "other liabilities",
            )),
            ("equity_capital", "Vốn chủ sở hữu", "Vốn và quỹ", (
                "von chu so huu", "von cua to chuc tin dung", "quy cua to chuc",
                "chenh lech", "loi nhuan chua phan phoi", "minority", "equity",
            )),
        ],
        "default": ("other_bs", "Khác", "Bảng cân đối khác"),
    },
    "IS": {
        "bank": [
            ("interest_income", "Thu nhập lãi", "Thu nhập lãi và chi phí lãi", (
                "thu nhap lai", "chi phi lai", "lai thuan", "interest",
            )),
            ("non_interest_income", "Ngoài lãi", "Dịch vụ và kinh doanh vốn", (
                "dich vu", "ngoai hoi", "vang", "chung khoan", "gop von",
                "mua co phan", "trading", "service", "foreign exchange",
            )),
            ("other_income", "Thu nhập khác", "Hoạt động khác", (
                "hoat dong khac", "thu nhap khac", "chi phi khac", "other",
            )),
            ("operating_expense", "Chi phí hoạt động", "Vận hành ngân hàng", (
                "chi phi hoat dong", "operating expenses", "admin",
            )),
            ("provision", "Dự phòng", "Chi phí dự phòng rủi ro tín dụng", (
                "du phong", "rui ro tin dung", "provision",
            )),
            ("bottom_line", "Kết quả cuối kỳ", "Lợi nhuận sau thuế", (
                "loi nhuan", "thue", "co dong thieu so", "ngan hang me",
                "profit", "tax",
            )),
        ],
        "default": ("other_is", "Khác", "Báo cáo thu nhập khác"),
    },
    "CF": {
        "bank": [
            ("cashflow_operating", "HĐKD", "Dòng tiền từ hoạt động kinh doanh", (
                "kinh doanh", "operating",
            )),
            ("cashflow_investing", "HĐĐT", "Dòng tiền từ hoạt động đầu tư", (
                "dau tu", "investing",
            )),
            ("cashflow_financing", "HĐTC", "Dòng tiền từ hoạt động tài chính", (
                "tai chinh", "financing",
            )),
            ("cashflow_summary", "Tổng hợp", "Tiền và tương đương tiền", (
                "luu chuyen tien thuan", "tien dau ky", "tien cuoi ky",
                "cash and cash equivalents", "net cash",
            )),
        ],
        "default": ("other_cf", "Khác", "Lưu chuyển tiền tệ khác"),
    },
}

NON_FINANCIAL_LEVELS = {
    "BS": [
        ("asset_current", "Tài sản", "Tài sản ngắn hạn", (
            "tai san ngan han", "tien", "dau tu tai chinh ngan han",
            "phai thu ngan han", "hang ton kho", "current assets", "inventory",
        )),
        ("asset_noncurrent", "Tài sản", "Tài sản dài hạn", (
            "tai san dai han", "phai thu dai han", "tai san co dinh",
            "bat dong san dau tu", "xay dung co ban", "dau tu tai chinh dai han",
            "long term", "fixed assets", "non current assets",
        )),
        ("liability", "Nguồn vốn", "Nợ phải trả", (
            "no phai tra", "vay", "thue", "phai tra", "chi phi phai tra",
            "liabilities", "borrowings", "payables",
        )),
        ("equity", "Nguồn vốn", "Vốn chủ sở hữu", (
            "von chu so huu", "von gop", "thang du", "co phieu quy", "quy",
            "loi nhuan sau thue chua phan phoi", "equity", "retained earnings",
        )),
    ],
    "IS": [
        ("revenue", "Doanh thu", "Doanh thu thuần", (
            "doanh thu", "revenue", "sales",
        )),
        ("direct_cost", "Chi phí trực tiếp", "Giá vốn hàng bán", (
            "gia von", "chi phi truc tiep", "cost of goods", "cost of sales",
        )),
        ("gross_profit", "Lợi nhuận gộp", "Biên lợi nhuận gộp", (
            "loi nhuan gop", "gross profit",
        )),
        ("financial_activity", "Hoạt động tài chính", "Doanh thu/chi phí tài chính", (
            "tai chinh", "lai vay", "financial",
        )),
        ("operating_expense", "Chi phí hoạt động", "Bán hàng và quản lý", (
            "ban hang", "quan ly", "operating", "selling", "admin",
        )),
        ("bottom_line", "Kết quả cuối kỳ", "Lợi nhuận sau thuế", (
            "loi nhuan", "thue", "eps", "profit", "tax",
        )),
    ],
    "CF": REPORT_LEVELS["CF"]["bank"],
}

FORMULA_COMPONENTS = {
    "total_assets": [
        ["current_assets", "non_current_assets"],
        ["current_assets", "long_term_assets"],
        [
            "cash_and_valuable_papers", "deposit_at_SBV", "treasury_bills",
            "deposit_at_FI", "trading_securities",
            "derivatives_and_other_financial_assets", "customer_loan",
            "investment_securities", "long_term_capital_investments",
            "fixed_assets", "investment_property", "other_assets",
        ],
    ],
    "liabilities": [
        ["current_liabilities", "long_term_liabilities"],
        ["current_liabilities", "non_current_liabilities"],
        [
            "debt_at_SBV_and_government", "debt_at_FI", "customer_deposit",
            "derivatives_and_other_financial_liabilities",
            "entrusted_investment_funds", "valuable_papers_issued",
            "other_liabilities",
        ],
    ],
    "equity": [
        ["capital_and_reserves", "other_reserves", "retained_earnings", "minority_interest"],
        ["credit_institution_capital", "credit_institution_reserves", "foreign_exchange_difference", "state_budget_and_other_funds", "minority_interest"],
    ],
    "owners_equity": [["capital_and_reserves"]],
    "capital_and_reserves": [
        [
            "paid_in_capital", "share_premium", "owners_other_capital",
            "treasury_shares", "differences_upon_asset_revaluation",
            "foreign_exchange_differences", "investment_and_development_funds",
            "financial_reserve_funds", "other_funds", "undistributed_earnings",
            "enterprise_arrangement_fund", "budget_sources_and_other_funds",
            "bonus_and_welfare_funds_before_2010", "minority_interests_before_2015",
        ],
    ],
    "paid_in_capital": [["common_shares", "preferred_shares"]],
    "undistributed_earnings": [
        [
            "beginning_accumulated_undistributed_earnings",
            "current_period_undistributed_earnings",
        ],
    ],
    "total_liabilities_and_equity": [["liabilities", "equity"]],
    "total_resource": [["liabilities", "equity"], ["liabilities", "owners_equity"]],
    "net_interest_income": [["interest_income", "interest_expenses"]],
    "net_service_income": [["service_income", "service_expenses"]],
    "customer_loan": [["customer_loan_gross", "customer_loan_provision"]],
    "gross_profit": [["revenue", "cost_of_goods_sold"]],
    "operating_profit": [["gross_profit", "financial_income", "financial_expenses", "selling_expenses", "general_admin_expenses"]],
    "profit_before_provision": [[
        "net_interest_income", "net_service_income", "net_foreign_exchange_income",
        "net_trading_securities_income", "net_investment_securities_income",
        "other_income", "dividend_income", "operating_expenses",
    ]],
    "profit_before_tax": [["operating_profit", "other_profit"], ["profit_before_provision", "credit_provision_expense"]],
    "profit": [["profit_before_tax", "current_income_tax_expense", "deferred_income_tax_expense"]],
    "net_cashflow": [["cashflow_operating", "cashflow_investing", "cashflow_financing"]],
    "cash_ending": [["cash_beginning", "net_cashflow"]],
}

GOLD_FEATURES = {
    "BS": [
        ("current_assets", None, "Tài sản ngắn hạn", "Current assets", 1000, 0, True),
        ("cash_and_cash_equivalents", "current_assets", "Tiền và các khoản tương đương tiền", "Cash and cash equivalents", 1010, 1, False),
        ("short_term_investments", "current_assets", "Các khoản đầu tư tài chính ngắn hạn", "Short-term financial investments", 1020, 1, False),
        ("accounts_receivable", "current_assets", "Các khoản phải thu ngắn hạn", "Short-term receivables", 1030, 1, False),
        ("inventory", "current_assets", "Hàng tồn kho", "Inventories", 1040, 1, False),
        ("other_current_assets", "current_assets", "Tài sản ngắn hạn khác", "Other current assets", 1050, 1, False),
        ("non_current_assets", None, "Tài sản dài hạn", "Non-current assets", 1100, 0, True),
        ("fixed_assets", "non_current_assets", "Tài sản cố định", "Fixed assets", 1110, 1, False),
        ("investment_property", "non_current_assets", "Bất động sản đầu tư", "Investment property", 1120, 1, False),
        ("long_term_investments", "non_current_assets", "Các khoản đầu tư tài chính dài hạn", "Long-term financial investments", 1130, 1, False),
        ("total_assets", None, "Tổng cộng tài sản", "Total assets", 1190, 0, True),
        ("liabilities", None, "Nợ phải trả", "Liabilities", 1200, 0, True),
        ("current_liabilities", "liabilities", "Nợ ngắn hạn", "Current liabilities", 1210, 1, False),
        ("non_current_liabilities", "liabilities", "Nợ dài hạn", "Non-current liabilities", 1220, 1, False),
        ("equity", None, "Vốn chủ sở hữu", "Owners' equity", 1300, 0, True),
        ("paid_in_capital", "equity", "Vốn đầu tư của chủ sở hữu", "Paid-in capital", 1310, 1, False),
        ("share_premium", "equity", "Thặng dư vốn cổ phần", "Share premium", 1320, 1, False),
        ("retained_earnings", "equity", "Lợi nhuận sau thuế chưa phân phối", "Retained earnings", 1330, 1, False),
        ("minority_interest", "equity", "Lợi ích của cổ đông thiểu số", "Minority interest", 1340, 1, False),
        ("total_liabilities_and_equity", None, "Tổng cộng nguồn vốn", "Total liabilities and equity", 1390, 0, True),
    ],
    "IS": [
        ("revenue", None, "Doanh thu thuần về bán hàng và cung cấp dịch vụ", "Net revenue", 2000, 0, True),
        ("cost_of_goods_sold", None, "Giá vốn hàng bán", "Cost of goods sold", 2010, 0, False),
        ("gross_profit", None, "Lợi nhuận gộp về bán hàng và cung cấp dịch vụ", "Gross profit", 2020, 0, True),
        ("financial_income", None, "Doanh thu hoạt động tài chính", "Financial income", 2030, 0, False),
        ("financial_expenses", None, "Chi phí tài chính", "Financial expenses", 2040, 0, False),
        ("selling_expenses", None, "Chi phí bán hàng", "Selling expenses", 2050, 0, False),
        ("general_admin_expenses", None, "Chi phí quản lý doanh nghiệp", "General and admin expenses", 2060, 0, False),
        ("operating_profit", None, "Lợi nhuận thuần từ hoạt động kinh doanh", "Operating profit", 2070, 0, True),
        ("other_profit", None, "Lợi nhuận khác", "Other profit", 2080, 0, False),
        ("associates_profit_loss", None, "Phần lợi nhuận/lỗ từ công ty liên kết liên doanh", "Share of profit/loss from associates and joint ventures", 2090, 0, False),
        ("profit_before_tax", None, "Tổng lợi nhuận kế toán trước thuế", "Profit before tax", 2100, 0, True),
        ("profit", None, "Lợi nhuận sau thuế thu nhập doanh nghiệp", "Profit after tax", 2110, 0, True),
        ("parent_profit", None, "Lợi nhuận sau thuế của cổ đông Công ty mẹ", "Profit attributable to parent company", 2120, 0, True),
        ("basic_eps", None, "Lãi cơ bản trên cổ phiếu (VNĐ)", "Basic EPS (VND)", 2130, 0, False),
        ("net_interest_income", None, "Thu nhập lãi thuần", "Net interest income", 2200, 0, True),
        ("interest_income", "net_interest_income", "Thu nhập từ lãi và các khoản thu nhập tương tự", "Interest and similar income", 2210, 1, False),
        ("interest_expenses", "net_interest_income", "Chi phí lãi và các chi phí tương tự", "Interest and similar expenses", 2220, 1, False),
        ("net_service_income", None, "Lãi/Lỗ thuần từ hoạt động dịch vụ", "Net service income", 2230, 0, True),
        ("service_income", "net_service_income", "Thu nhập từ hoạt động dịch vụ", "Service income", 2240, 1, False),
        ("service_expenses", "net_service_income", "Chi phí hoạt động dịch vụ", "Service expenses", 2250, 1, False),
        ("net_foreign_exchange_income", None, "Lãi/Lỗ thuần từ hoạt động kinh doanh ngoại hối", "Net foreign exchange income", 2260, 0, False),
        ("net_trading_securities_income", None, "Lãi/Lỗ thuần từ mua bán chứng khoán kinh doanh", "Net trading securities income", 2270, 0, False),
        ("net_investment_securities_income", None, "Lãi/Lỗ thuần từ mua bán chứng khoán đầu tư", "Net investment securities income", 2280, 0, False),
        ("other_income", None, "Lãi/Lỗ thuần từ hoạt động khác", "Net other operating income", 2290, 0, True),
        ("dividend_income", None, "Thu nhập từ hoạt động góp vốn mua cổ phần", "Dividend income", 2300, 0, False),
        ("operating_expenses", None, "Chi phí hoạt động", "Operating expenses", 2310, 0, False),
        ("profit_before_provision", None, "Lợi nhuận từ HĐKD trước chi phí dự phòng rủi ro tín dụng", "Profit before credit provision expense", 2320, 0, True),
        ("credit_provision_expense", None, "Chi phí dự phòng rủi ro tín dụng", "Credit provision expense", 2330, 0, False),
        ("current_income_tax_expense", None, "Chi phí thuế TNDN", "Corporate income tax expense", 2340, 0, False),
        ("deferred_income_tax_expense", None, "Chi phí thuế TNDN hoãn lại", "Deferred corporate income tax expense", 2341, 0, False),
        ("minority_interest_profit", None, "Lợi ích của cổ đông thiểu số và cổ tức ưu đãi", "Minority interests and preferred dividends", 2350, 0, False),
        ("adjusted_parent_profit", None, "LNST sau khi điều chỉnh Lợi ích của CĐTS và Cổ tức ưu đãi", "Adjusted profit after minority interests and preferred dividends", 2360, 0, True),
    ],
    "CF": [
        ("cashflow_operating", None, "Lưu chuyển tiền tệ từ hoạt động kinh doanh", "Cash flows from operating activities", 3000, 0, True),
        ("cashflow_investing", None, "Lưu chuyển tiền tệ từ hoạt động đầu tư", "Cash flows from investing activities", 3010, 0, True),
        ("cashflow_financing", None, "Lưu chuyển tiền tệ từ hoạt động tài chính", "Cash flows from financing activities", 3020, 0, True),
        ("net_cashflow", None, "Lưu chuyển tiền thuần trong kỳ", "Net cash flow during the period", 3030, 0, True),
        ("cash_beginning", None, "Tiền và tương đương tiền đầu kỳ", "Cash and cash equivalents at beginning of period", 3040, 0, True),
        ("cash_ending", None, "Tiền và tương đương tiền cuối kỳ", "Cash and cash equivalents at end of period", 3050, 0, True),
    ],
}

FINANCIAL_BS_FEATURES = [
    ("cash_and_valuable_papers", "total_assets", "Tiền mặt, chứng từ có giá trị, ngoại tệ, kim loại quý, đá quý", "Cash, valuable papers, foreign currencies and precious metals", 2000, 1, False),
    ("deposit_at_SBV", "total_assets", "Tiền gửi tại NHNN", "Balances with the State Bank of Vietnam", 2010, 1, False),
    ("treasury_bills", "total_assets", "Tín phiếu kho bạc và các giấy tờ có giá ngắn hạn đủ tiêu chuẩn khác", "Treasury bills and eligible short-term valuable papers", 2020, 1, False),
    ("deposit_at_FI", "total_assets", "Tiền, vàng gửi tại các TCTD khác và cho vay các TCTD khác", "Placements with and loans to other credit institutions", 2030, 1, True),
    ("trading_securities", "total_assets", "Chứng khoán kinh doanh", "Trading securities", 2040, 1, True),
    ("trading_securities_gross", "trading_securities", "Chứng khoán kinh doanh", "Trading securities - gross", 2041, 2, False),
    ("trading_securities_provision", "trading_securities", "Dự phòng giảm giá chứng khoán kinh doanh", "Trading securities provision", 2042, 2, False),
    ("derivatives_and_other_financial_assets", "total_assets", "Các công cụ tài chính phái sinh và các tài sản tài chính khác", "Derivatives and other financial assets", 2050, 1, False),
    ("customer_loan", "total_assets", "Cho vay khách hàng", "Loans to customers", 2060, 1, True),
    ("customer_loan_gross", "customer_loan", "Cho vay khách hàng", "Loans to customers - gross", 2061, 2, False),
    ("customer_loan_provision", "customer_loan", "Dự phòng rủi ro cho vay khách hàng", "Loan loss provision", 2062, 2, False),
    ("investment_securities", "total_assets", "Chứng khoán đầu tư", "Investment securities", 2070, 1, True),
    ("available_for_sale_securities", "investment_securities", "Chứng khoán đầu tư sẵn sàng để bán", "Available-for-sale securities", 2071, 2, False),
    ("held_to_maturity_securities", "investment_securities", "Chứng khoán đầu tư giữ đến ngày đáo hạn", "Held-to-maturity securities", 2072, 2, False),
    ("investment_securities_provision", "investment_securities", "Dự phòng giảm giá chứng khoán đầu tư", "Investment securities provision", 2073, 2, False),
    ("long_term_capital_investments", "total_assets", "Góp vốn đầu tư dài hạn", "Long-term capital investments", 2080, 1, True),
    ("investment_in_associates", "long_term_capital_investments", "Đầu tư vào công ty liên doanh, liên kết", "Investments in associates and joint ventures", 2081, 2, False),
    ("investment_in_subsidiaries", "long_term_capital_investments", "Đầu tư vào công ty con", "Investments in subsidiaries", 2082, 2, False),
    ("long_term_investment_provision", "long_term_capital_investments", "Dự phòng giảm giá đầu tư dài hạn", "Long-term investment provision", 2083, 2, False),
    ("other_assets", "total_assets", "Tài sản Có khác", "Other assets", 2090, 1, True),
    ("debt_at_SBV_and_government", "liabilities", "Các khoản nợ Chính phủ và NHNN", "Borrowings from Government and the SBV", 2200, 1, False),
    ("debt_at_FI", "liabilities", "Tiền gửi và vay các TCTD khác", "Deposits and borrowings from other credit institutions", 2210, 1, True),
    ("customer_deposit", "liabilities", "Tiền gửi khách hàng", "Customer deposits", 2220, 1, False),
    ("derivatives_and_other_financial_liabilities", "liabilities", "Các công cụ tài chính phái sinh và các khoản nợ tài chính khác", "Derivatives and other financial liabilities", 2230, 1, False),
    ("entrusted_investment_funds", "liabilities", "Vốn tài trợ, uỷ thác đầu tư mà ngân hàng chịu rủi ro", "Entrusted investment funds exposed to bank risk", 2240, 1, False),
    ("valuable_papers_issued", "liabilities", "Phát hành giấy tờ có giá", "Valuable papers issued", 2250, 1, False),
    ("other_liabilities", "liabilities", "Các khoản nợ khác", "Other liabilities", 2260, 1, True),
    ("capital_and_reserves", "equity", "Vốn và các quỹ", "Capital and reserves", 2300, 1, True),
    ("credit_institution_capital", "capital_and_reserves", "Vốn của tổ chức tín dụng", "Credit institution capital", 2301, 2, False),
    ("credit_institution_reserves", "capital_and_reserves", "Quỹ của tổ chức tín dụng", "Credit institution reserves", 2302, 2, False),
    ("foreign_exchange_difference", "capital_and_reserves", "Chênh lệch tỷ giá hối đoái", "Foreign exchange difference", 2303, 2, False),
    ("asset_revaluation_difference", "capital_and_reserves", "Chênh lệch đánh giá lại tài sản", "Asset revaluation difference", 2304, 2, False),
    ("state_budget_and_other_funds", "capital_and_reserves", "Vốn ngân sách nhà nước và quỹ khác", "State budget and other funds", 2305, 2, False),
    ("bank_other_reserves", "capital_and_reserves", "Các quỹ khác", "Other bank reserves", 2306, 2, False),
]

GOLD_FEATURES["BS"].extend(FINANCIAL_BS_FEATURES)

FEATURE_BY_REPORT = {
    report_type: {criteria: feature for criteria, *feature in features}
    for report_type, features in GOLD_FEATURES.items()
}

FEATURE_CRITERIA_ALIASES = {
    "BS": {
        "cash": "cash_and_cash_equivalents",
        "cash_equivalents": "cash_and_cash_equivalents",
        "short_term_receivables": "accounts_receivable",
        "accounts_receivable": "accounts_receivable",
        "inventories_net": "inventory",
        "inventory": "inventory",
        "investment_properties": "investment_property",
        "long_term_assets": "non_current_assets",
        "long_term_liabilities": "non_current_liabilities",
        "owners_equity": "equity",
        "undistributed_earnings": "retained_earnings",
        "minority_interests": "minority_interest",
        "total_resource": "total_liabilities_and_equity",
        "tien_mat_chung_tu_co_gia_tri_ngoai_te_kim_loai_quy_da_quy": "cash_and_valuable_papers",
        "tien_gui_tai_nhnn": "deposit_at_SBV",
        "tien_gui_tai_ngan_hang_nha_nuoc": "deposit_at_SBV",
        "tien_gui_tai_ngan_hang_nha_nuoc_viet_nam": "deposit_at_SBV",
        "balances_with_the_sbv": "deposit_at_SBV",
        "balances_with_state_bank_of_vietnam": "deposit_at_SBV",
        "tin_phieu_kho_bac_va_cac_giay_to_co_gia_ngan_han_du_tieu_chuan_khac": "treasury_bills",
        "tien_vang_gui_tai_cac_tctd_khac_va_cho_vay_cac_tctd_khac": "deposit_at_FI",
        "tien_gui_va_cho_vay_cac_tctd_khac": "deposit_at_FI",
        "tien_gui_tai_cac_tctd_khac_va_cho_vay_cac_tctd_khac": "deposit_at_FI",
        "placements_with_and_loans_to_other_credit_institutions": "deposit_at_FI",
        "deposits_with_and_loans_to_other_credit_institutions": "deposit_at_FI",
        "chung_khoan_kinh_doanh": "trading_securities",
        "du_phong_giam_gia_chung_khoan_kinh_doanh": "trading_securities_provision",
        "cac_cong_cu_tai_chinh_phai_sinh_va_cac_tai_san_tai_chinh_khac": "derivatives_and_other_financial_assets",
        "cac_cong_cu_tai_chinh_phai_sinh_va_khoan_no_tai_chinh_khac": "derivatives_and_other_financial_assets",
        "cho_vay_khach_hang": "customer_loan",
        "_cho_vay_khach_hang": "customer_loan_gross",
        "du_phong_rui_ro_cho_vay_khach_hang": "customer_loan_provision",
        "chung_khoan_dau_tu": "investment_securities",
        "chung_khoan_dau_tu_san_sang_de_ban": "available_for_sale_securities",
        "chung_khoan_dau_tu_giu_den_ngay_dao_han": "held_to_maturity_securities",
        "du_phong_giam_gia_chung_khoan_dau_tu": "investment_securities_provision",
        "gop_von_dau_tu_dai_han": "long_term_capital_investments",
        "dau_tu_vao_cong_ty_lien_doanh": "investment_in_associates",
        "dau_tu_vao_cong_ty_lien_doanh_lien_ket": "investment_in_associates",
        "dau_tu_vao_cong_ty_con": "investment_in_subsidiaries",
        "du_phong_giam_gia_dau_tu_dai_han": "long_term_investment_provision",
        "tai_san_co_khac": "other_assets",
        "cac_khoan_no_chinh_phu_va_nhnn": "debt_at_SBV_and_government",
        "cac_khoan_no_chinh_phu_va_nhnn_viet_nam": "debt_at_SBV_and_government",
        "tien_gui_va_vay_cac_tctd_khac": "debt_at_FI",
        "tien_gui_va_vay_cac_to_chuc_tin_dung_khac": "debt_at_FI",
        "tien_gui_khach_hang": "customer_deposit",
        "tien_gui_cua_khach_hang": "customer_deposit",
        "cac_cong_cu_tai_chinh_phai_sinh_va_cac_khoan_no_tai_chinh_khac": "derivatives_and_other_financial_liabilities",
        "von_tai_tro_uy_thac_dau_tu_ma_ngan_hang_chiu_rui_ro": "entrusted_investment_funds",
        "von_tai_tro_uy_thac_dau_tu_cua_cp_va_cac_to_chuc_td_khac": "entrusted_investment_funds",
        "phat_hanh_giay_to_co_gia": "valuable_papers_issued",
        "cac_khoan_no_khac": "other_liabilities",
        "von_va_cac_quy": "capital_and_reserves",
        "von_cua_to_chuc_tin_dung": "credit_institution_capital",
        "quy_cua_to_chuc_tin_dung": "credit_institution_reserves",
        "chenh_lech_ty_gia_hoi_doai": "foreign_exchange_difference",
        "chenh_lech_danh_gia_lai_tai_san": "asset_revaluation_difference",
        "von_ngan_sach_nha_nuoc_va_quy_khac": "state_budget_and_other_funds",
        "_cac_quy_khac": "bank_other_reserves",
        "co_dong_thieu_so": "minority_interest",
    },
    "IS": {
        "net_sales": "revenue",
        "net_revenue": "revenue",
        "cost_of_sales": "cost_of_goods_sold",
        "cogs": "cost_of_goods_sold",
        "gia_von_hang_ban": "cost_of_goods_sold",
        "lai_gop": "gross_profit",
        "loi_nhuan_gop": "gross_profit",
        "loi_nhuan_gop_ve_ban_hang_va_cung_cap_dich_vu": "gross_profit",
        "thu_nhap_tai_chinh": "financial_income",
        "doanh_thu_hoat_dong_tai_chinh": "financial_income",
        "chi_phi_tai_chinh": "financial_expenses",
        "chi_phi_ban_hang": "selling_expenses",
        "sales_expenses": "selling_expenses",
        "chi_phi_quan_ly_dn": "general_admin_expenses",
        "chi_phi_quan_ly_doanh_nghiep": "general_admin_expenses",
        "general_and_admin_expenses": "general_admin_expenses",
        "admin_expenses": "general_admin_expenses",
        "lai_lo_tu_hdkd": "operating_profit",
        "lai_lo_tu_hoat_dong_kinh_doanh": "operating_profit",
        "loi_nhuan_thuan_tu_hoat_dong_kinh_doanh": "operating_profit",
        "operating_profit_loss": "operating_profit",
        "net_other_income_expenses": "other_profit",
        "lai_lo_trong_cty_lien_doanh_lien_ket": "associates_profit_loss",
        "lai_lo_trong_cong_ty_lien_doanh_lien_ket": "associates_profit_loss",
        "lai_lo_tu_cong_ty_lien_doanh": "associates_profit_loss",
        "phan_loi_nhuan_lo_tu_cong_ty_lien_ket_lien_doanh": "associates_profit_loss",
        "phan_loi_nhuan_lo_tu_cong_ty_lien_doanh_lien_ket": "associates_profit_loss",
        "income_from_investments_in_other_entities": "associates_profit_loss",
        "gain_loss_from_joint_ventures_from_2015": "associates_profit_loss",
        "ln_truoc_thue": "profit_before_tax",
        "loi_nhuan_truoc_thue": "profit_before_tax",
        "tong_loi_nhuan_ke_toan_truoc_thue": "profit_before_tax",
        "net_accounting_profit_loss_before_tax": "profit_before_tax",
        "net_profit_loss_after_tax": "profit",
        "attributable_to_parent_company": "parent_profit",
        "eps_basic_vnd": "basic_eps",
        "thu_nhap_lai_thuan": "net_interest_income",
        "thu_nhap_lai_va_cac_khoan_thu_nhap_tuong_tu": "interest_income",
        "thu_nhap_tu_lai_va_cac_khoan_thu_nhap_tuong_tu": "interest_income",
        "interest_and_similar_income": "interest_income",
        "chi_phi_lai_va_cac_chi_phi_tuong_tu": "interest_expenses",
        "interest_and_similar_expenses": "interest_expenses",
        "lai_lo_thuan_tu_hoat_dong_dich_vu": "net_service_income",
        "lai_thuan_tu_hoat_dong_dich_vu": "net_service_income",
        "thu_nhap_tu_hoat_dong_dich_vu": "service_income",
        "chi_phi_hoat_dong_dich_vu": "service_expenses",
        "lai_lo_thuan_tu_hoat_dong_kinh_doanh_ngoai_hoi": "net_foreign_exchange_income",
        "lai_lo_thuan_tu_mua_ban_chung_khoan_kinh_doanh": "net_trading_securities_income",
        "lai_lo_thuan_tu_mua_ban_chung_khoan_dau_tu": "net_investment_securities_income",
        "lai_lo_thuan_tu_hoat_dong_khac": "other_income",
        "thu_nhap_tu_hoat_dong_gop_von_mua_co_phan": "dividend_income",
        "thu_nhap_tu_gop_von_mua_co_phan": "dividend_income",
        "chi_phi_hoat_dong": "operating_expenses",
        "loi_nhuan_tu_hdkd_truoc_chi_phi_du_phong_rui_ro_tin_dung": "profit_before_provision",
        "loi_nhuan_tu_hoat_dong_kinh_doanh_truoc_chi_phi_du_phong_rui_ro_tin_dung": "profit_before_provision",
        "chi_phi_du_phong_rui_ro_tin_dung": "credit_provision_expense",
        "chi_phi_thue_tndn": "current_income_tax_expense",
        "chi_phi_thue_tndn_hien_hanh": "current_income_tax_expense",
        "business_income_tax_current": "current_income_tax_expense",
        "business_income_tax_expenses": "current_income_tax_expense",
        "corporate_income_tax_expenses": "current_income_tax_expense",
        "chi_phi_thue_tndn_hoan_lai": "deferred_income_tax_expense",
        "business_income_tax_deferred": "deferred_income_tax_expense",
        "loi_ich_cua_co_dong_thieu_so_va_co_tuc_uu_dai": "minority_interest_profit",
        "lnst_sau_khi_dieu_chinh_loi_ich_cua_cdts_va_co_tuc_uu_dai": "adjusted_parent_profit",
    },
    "CF": {
        "luu_chuyen_tien_te_rong_tu_cac_hoat_dong_sxkd": "cashflow_operating",
        "luu_chuyen_tien_te_rong_tu_cac_hoat_dong_xskd": "cashflow_operating",
        "luu_chuyen_tien_te_tu_hoat_dong_kinh_doanh": "cashflow_operating",
        "luu_chuyen_tien_tu_hoat_dong_kinh_doanh": "cashflow_operating",
        "luu_chuyen_tu_hoat_dong_kinh_doanh": "cashflow_operating",
        "luu_chuyen_tien_thuan_tu_hoat_dong_kinh_doanh": "cashflow_operating",
        "net_cash_inflows_outflows_from_operating_activities": "cashflow_operating",
        "net_cash_from_operating_activities": "cashflow_operating",
        "net_cash_flows_from_operating_activities_before_cit": "cashflow_operating",
        "luu_chuyen_tien_te_tu_hoat_dong_dau_tu": "cashflow_investing",
        "luu_chuyen_tien_tu_hoat_dong_dau_tu": "cashflow_investing",
        "luu_chuyen_tu_hoat_dong_dau_tu": "cashflow_investing",
        "luu_chuyen_tien_thuan_tu_hoat_dong_dau_tu": "cashflow_investing",
        "net_cash_inflows_outflows_from_investing_activities": "cashflow_investing",
        "net_cash_from_investing_activities": "cashflow_investing",
        "luu_chuyen_tien_te_tu_hoat_dong_tai_chinh": "cashflow_financing",
        "luu_chuyen_tien_tu_hoat_dong_tai_chinh": "cashflow_financing",
        "luu_chuyen_tu_hoat_dong_tai_chinh": "cashflow_financing",
        "luu_chuyen_tien_thuan_tu_hoat_dong_tai_chinh": "cashflow_financing",
        "net_cash_inflows_outflows_from_financing_activities": "cashflow_financing",
        "net_cash_from_financing_activities": "cashflow_financing",
        "net_increase_in_cash_and_cash_equivalents": "net_cashflow",
        "net_increase_decrease_in_cash_and_cash_equivalents": "net_cashflow",
        "tien_va_tuong_duong_tien": "cash_beginning",
        "tien_va_tuong_duong_tien_dau_ky": "cash_beginning",
        "tien_va_cac_khoan_tuong_duong_tien": "cash_beginning",
        "tien_va_cac_khoan_tuong_duong_tien_dau_ky": "cash_beginning",
        "cash_and_cash_equivalents_at_the_beginning_of_period": "cash_beginning",
        "cash_and_bank_deposit_at_the_beginning_of_the_period": "cash_beginning",
        "tien_va_tuong_duong_tien_cuoi_ky": "cash_ending",
        "tien_va_cac_khoan_tuong_duong_tien_cuoi_ky": "cash_ending",
        "cash_and_cash_equivalents_at_the_end_of_period": "cash_ending",
        "cash_and_cash_equivalents_at_end_of_the_period": "cash_ending",
    },
}

FEATURE_PREFERRED_TERMS = {
    "revenue": ("doanh thu thuan", "net sales", "net revenue"),
    "gross_profit": ("loi nhuan gop ve ban hang va cung cap dich vu", "loi nhuan gop", "lai gop", "gross profit"),
    "financial_income": ("doanh thu hoat dong tai chinh", "thu nhap tai chinh", "financial income"),
    "financial_expenses": ("chi phi tai chinh", "financial expenses"),
    "selling_expenses": ("chi phi ban hang", "selling expenses"),
    "general_admin_expenses": ("chi phi quan ly doanh nghiep", "chi phi quan ly dn", "general admin"),
    "operating_profit": ("loi nhuan thuan tu hoat dong kinh doanh", "lai lo tu hdkd", "operating profit"),
    "other_profit": ("loi nhuan khac", "other profit", "net other income"),
    "associates_profit_loss": ("lien doanh lien ket", "cong ty lien ket", "cong ty lien doanh", "associates"),
    "profit_before_tax": ("tong loi nhuan ke toan truoc thue", "loi nhuan truoc thue", "ln truoc thue", "profit before tax"),
    "profit": ("loi nhuan sau thue thu nhap doanh nghiep", "loi nhuan sau thue", "net profit loss after tax"),
    "parent_profit": ("co dong cong ty me", "parent company", "attributable to parent"),
    "inventory": ("hang ton kho rong", "inventories net", "hang ton kho"),
    "deposit_at_SBV": ("tien gui tai nhnn", "ngan hang nha nuoc", "state bank"),
    "deposit_at_FI": ("tctd khac", "credit institutions"),
    "customer_loan": ("cho vay khach hang", "loans to customers"),
    "customer_deposit": ("tien gui khach hang", "tien gui cua khach hang", "customer deposits"),
    "capital_and_reserves": ("von va cac quy", "capital and reserves"),
    "net_interest_income": ("thu nhap lai thuan", "net interest income"),
    "interest_income": ("thu nhap tu lai", "thu nhap lai va cac khoan", "interest and similar income"),
    "interest_expenses": ("chi phi lai va cac chi phi", "interest and similar expenses"),
    "net_service_income": ("lai lo thuan tu hoat dong dich vu", "lai thuan tu hoat dong dich vu"),
    "service_income": ("thu nhap tu hoat dong dich vu", "service income"),
    "service_expenses": ("chi phi hoat dong dich vu", "service expenses"),
    "net_foreign_exchange_income": ("kinh doanh ngoai hoi", "foreign exchange"),
    "net_trading_securities_income": ("chung khoan kinh doanh", "trading securities"),
    "net_investment_securities_income": ("chung khoan dau tu", "investment securities"),
    "other_income": ("lai lo thuan tu hoat dong khac", "other operating income"),
    "dividend_income": ("gop von mua co phan", "dividend income"),
    "operating_expenses": ("chi phi hoat dong", "operating expenses"),
    "profit_before_provision": ("truoc chi phi du phong rui ro tin dung", "before credit provision"),
    "credit_provision_expense": ("chi phi du phong rui ro tin dung", "credit provision"),
    "current_income_tax_expense": ("chi phi thue tndn", "corporate income tax"),
    "minority_interest_profit": ("loi ich cua co dong thieu so", "preferred dividends"),
    "adjusted_parent_profit": ("lnst sau khi dieu chinh", "adjusted profit"),
    "cashflow_operating": (
        "luu chuyen tien te rong tu cac hoat dong sxkd",
        "luu chuyen tien te rong tu cac hoat dong xskd",
        "luu chuyen tien te tu hoat dong kinh doanh",
        "luu chuyen tien thuan tu hoat dong kinh doanh",
        "net cash",
    ),
    "cashflow_investing": (
        "luu chuyen tu hoat dong dau tu",
        "luu chuyen tien te tu hoat dong dau tu",
        "luu chuyen tien thuan tu hoat dong dau tu",
        "net cash",
    ),
    "cashflow_financing": (
        "luu chuyen tien tu hoat dong tai chinh",
        "luu chuyen tien te tu hoat dong tai chinh",
        "luu chuyen tien thuan tu hoat dong tai chinh",
        "net cash",
    ),
    "cash_beginning": (
        "tien va tuong duong tien dau ky",
        "tien va cac khoan tuong duong tien dau ky",
        "cash and cash equivalents at beginning",
    ),
    "cash_ending": (
        "tien va tuong duong tien cuoi ky",
        "tien va cac khoan tuong duong tien cuoi ky",
        "cash and cash equivalents at end",
    ),
}


def _ascii_key(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_numbering(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    return re.sub(
        r"^\s*(?:[A-Z]\.|[IVXLCDM]+\.\s*|\d+[\.)]\s*)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _text(value: object) -> str:
    return "" if pd.isna(value) else str(value)


def _slug_key(value: object) -> str:
    key = _ascii_key(value)
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_")


def _canonical_feature_criteria(row: pd.Series) -> str | None:
    report_type = row.get("report_type")
    feature_map = FEATURE_BY_REPORT.get(report_type)
    if not feature_map:
        return None

    aliases = FEATURE_CRITERIA_ALIASES.get(report_type, {})
    for col in ("criteria", "item_id", "line_item_key", "item_name_vi", "item_name_en"):
        candidate = _slug_key(row.get(col))
        if not candidate:
            continue
        if candidate in feature_map:
            return candidate
        mapped = aliases.get(candidate)
        if mapped in feature_map:
            return mapped

    return None


def _feature_match_score(row: pd.Series, canonical: str) -> int:
    score = 0
    for col in ("criteria", "item_id", "line_item_key"):
        if _slug_key(row.get(col)) == canonical:
            score += 10

    text_key = _ascii_key(
        " ".join(
            _text(row.get(col))
            for col in ("criteria", "item_id", "item_name_vi", "item_name_en")
        )
    )
    for term in FEATURE_PREFERRED_TERMS.get(canonical, ()):
        if term in text_key:
            score += 25

    return score


def _feature_value(feature: tuple[object, ...], index: int) -> object:
    return feature[index]


def _filter_gold_features(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    out["_feature_criteria"] = out.apply(_canonical_feature_criteria, axis=1)
    out = out[out["_feature_criteria"].notna()].copy()
    if out.empty:
        return out.drop(columns=["_feature_criteria"], errors="ignore")

    out["_feature_score"] = out.apply(
        lambda row: _feature_match_score(row, row["_feature_criteria"]),
        axis=1,
    )
    out["_has_value"] = out["value"].notna()
    out = out.sort_values(
        [
            "ticker",
            "year",
            "quarter",
            "report_type",
            "_feature_criteria",
            "_feature_score",
            "_has_value",
            "display_order",
        ],
        ascending=[True, True, True, True, True, False, False, True],
    )
    out = out.drop_duplicates(
        ["ticker", "year", "quarter", "report_type", "_feature_criteria"],
        keep="first",
    ).copy()

    feature_series = [
        FEATURE_BY_REPORT[report_type][criteria]
        for report_type, criteria in zip(out["report_type"], out["_feature_criteria"])
    ]

    out["criteria"] = out["_feature_criteria"]
    out["standard_name"] = out["_feature_criteria"]
    out["item_id"] = out["_feature_criteria"]
    out["line_item_key"] = out["_feature_criteria"]
    out["item_code"] = out["_feature_criteria"]
    out["parent_line_item_key"] = [_feature_value(feature, 0) for feature in feature_series]
    out["parent_item_code"] = out["parent_line_item_key"]
    out["item_name_vi"] = [_feature_value(feature, 1) for feature in feature_series]
    out["item_name_en"] = [_feature_value(feature, 2) for feature in feature_series]
    out["display_label"] = out["item_name_vi"]
    out["display_order"] = [_feature_value(feature, 3) for feature in feature_series]
    out["level"] = [_feature_value(feature, 4) for feature in feature_series]
    out["is_total"] = [_feature_value(feature, 5) for feature in feature_series]

    frames = []
    for _, group in out.groupby(
        ["ticker", "year", "quarter", "report_type"],
        dropna=False,
        sort=False,
    ):
        group = group.copy()
        valid_keys = set(group["line_item_key"].astype(str))
        group["parent_line_item_key"] = group["parent_line_item_key"].where(
            group["parent_line_item_key"].astype(str).isin(valid_keys),
            None,
        )
        group["parent_item_code"] = group["parent_line_item_key"]
        frames.append(group)
    out = pd.concat(frames, ignore_index=True)

    parent_keys = set(out["parent_line_item_key"].dropna().astype(str))
    out["is_leaf"] = ~out["line_item_key"].astype(str).isin(parent_keys)

    return out.drop(columns=["_feature_criteria", "_feature_score", "_has_value"])


def _industry_group(industry: object, subindustry: object) -> str:
    key = _ascii_key(f"{industry} {subindustry}")
    if any(token in key for token in ("ngan hang", "bank")):
        return "bank"
    if any(token in key for token in ("dich vu tai chinh", "financial services")):
        return "financial_services"
    if any(token in key for token in ("chung khoan", "securities", "brokerage")):
        return "securities"
    if any(token in key for token in ("bao hiem", "insurance")):
        return "insurance"
    return "non_financial"


def _rules_for(report_type: str, industry_group: str):
    if industry_group in FINANCIAL_REPORT_GROUPS:
        return REPORT_LEVELS.get(report_type, {}).get("bank", [])
    return NON_FINANCIAL_LEVELS.get(report_type, [])


def _default_for(report_type: str, industry_group: str):
    if industry_group in FINANCIAL_REPORT_GROUPS:
        return REPORT_LEVELS.get(report_type, {}).get("default", ("other", "Khác", "Khác"))
    return ("other", "Khác", "Khác")


def _classify_line(row: pd.Series) -> pd.Series:
    report_type = row.get("report_type")
    industry_group = row.get("industry_group") or "non_financial"
    key = _ascii_key(
        " ".join(
            _text(row.get(col))
            for col in ("criteria", "item_id", "item_name_vi", "item_name_en")
        )
    )

    mapping_code, level_1, level_2 = _default_for(report_type, industry_group)
    for code, candidate_level_1, candidate_level_2, keywords in _rules_for(
        report_type, industry_group
    ):
        if any(keyword in key for keyword in keywords):
            mapping_code = code
            level_1 = candidate_level_1
            level_2 = candidate_level_2
            break

    display_label = row.get("item_name_vi")
    level_3 = _strip_numbering(display_label)
    return pd.Series(
        {
            "standard_name": row.get("criteria") or mapping_code,
            "level_1": level_1,
            "level_2": level_2,
            "level_3": level_3,
            "display_label": display_label,
            "sign_rule": "as_reported",
            "mapping_source": "docx_keyword_rules",
        }
    )


def _formula_from_components(
    row_index: str,
    criteria: object,
    criteria_to_index: dict[str, str],
) -> str | None:
    for components in FORMULA_COMPONENTS.get(str(criteria), []):
        if all(component in criteria_to_index for component in components):
            return f"{row_index} = " + " + ".join(
                criteria_to_index[component] for component in components
            )
    return None


def _hierarchy_path(
    item_code: object,
    parent_by_item: dict[str, str | None],
    index_by_item: dict[str, str],
) -> str:
    code = str(item_code)
    path = []
    seen = set()
    while code and code not in seen:
        seen.add(code)
        path.append(index_by_item.get(code, code))
        parent = parent_by_item.get(code)
        if parent is None or pd.isna(parent):
            break
        code = str(parent)
    return " > ".join(reversed(path))


def _add_hierarchy_metadata(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    frames = []
    group_cols = ["ticker", "year", "quarter", "statement_type"]
    for _, group in df.groupby(group_cols, dropna=False, sort=False):
        group = group.sort_values(["display_order", "item_code"]).copy()
        group["line_no"] = range(1, len(group) + 1)
        group["line_index"] = "(" + group["line_no"].astype(str) + ")"

        index_by_item = dict(zip(group["item_code"].astype(str), group["line_index"]))
        parent_by_item = dict(
            zip(group["item_code"].astype(str), group["parent_item_code"])
        )
        criteria_to_index = dict(zip(group["criteria"].astype(str), group["line_index"]))

        child_map = (
            group.dropna(subset=["parent_item_code"])
            .groupby("parent_item_code")["item_code"]
            .apply(lambda s: [str(v) for v in s.tolist()])
            .to_dict()
        )

        group["parent_line_index"] = group["parent_item_code"].map(
            lambda code: index_by_item.get(str(code)) if pd.notna(code) else None
        )
        group["child_item_codes"] = group["item_code"].map(
            lambda code: ",".join(child_map.get(str(code), []))
        )
        group["children_count"] = group["item_code"].map(
            lambda code: len(child_map.get(str(code), []))
        )
        group["has_children"] = group["children_count"] > 0
        group["is_expandable"] = group["has_children"]
        group["default_expanded"] = group["is_expandable"] & (
            group["level"].fillna(1).astype(int) <= 1
        )
        group["hierarchy_depth"] = group["level"].fillna(1).astype(int)
        group["visible_by_default"] = group["hierarchy_depth"] <= 1
        group["hierarchy_path"] = group["item_code"].map(
            lambda code: _hierarchy_path(code, parent_by_item, index_by_item)
        )
        group["classification_path"] = (
            group[["level_1", "level_2", "level_3"]]
            .fillna("")
            .agg(lambda parts: " > ".join([p for p in parts if p]), axis=1)
        )

        formula_by_item = {}
        for item_code, children in child_map.items():
            parent_index = index_by_item.get(str(item_code))
            child_indexes = [
                index_by_item[str(child)]
                for child in children
                if str(child) in index_by_item
            ]
            if parent_index and child_indexes:
                formula_by_item[str(item_code)] = (
                    f"{parent_index} = " + " + ".join(child_indexes)
                )

        group["calculation_formula"] = group.apply(
            lambda row: formula_by_item.get(str(row["item_code"]))
            or _formula_from_components(
                row["line_index"],
                row["criteria"],
                criteria_to_index,
            ),
            axis=1,
        )
        frames.append(group)

    return pd.concat(frames, ignore_index=True)


@asset(
    partitions_def=report_partitions,
    io_manager_key="minio_io_manager",
    ins={
        "reports": AssetIn(["silver", "silver_reports"]),
        "overview": AssetIn(
            ["silver", "company_info", "silver_overview"],
            metadata={
                "load_latest_partition": True,
                "allow_unpartitioned_fallback": True,
            },
            partition_mapping=AllPartitionMapping(),
        ),
    },
    group_name="gold",
    key_prefix=["gold"],
)
def gold_reports(
    reports: pd.DataFrame,
    overview: pd.DataFrame,
) -> Output[pd.DataFrame]:
    df = reports.copy()

    overview_cols = ["ticker", "industry", "subindustry"]
    if overview is None or overview.empty:
        overview_dim = pd.DataFrame(columns=overview_cols)
    else:
        overview_dim = overview.copy()
        for col in overview_cols:
            if col not in overview_dim.columns:
                overview_dim[col] = None
        if "date_fetched" in overview_dim.columns:
            overview_dim["date_fetched"] = pd.to_datetime(
                overview_dim["date_fetched"], errors="coerce"
            )
            overview_dim = overview_dim.sort_values(["ticker", "date_fetched"])
        elif "_partition_key" in overview_dim.columns:
            overview_dim = overview_dim.sort_values(["ticker", "_partition_key"])
        overview_dim = overview_dim[overview_cols].drop_duplicates("ticker", keep="last")

    df = df.merge(overview_dim, on="ticker", how="left")
    df["industry_group"] = [
        _industry_group(industry, subindustry)
        for industry, subindustry in zip(df["industry"], df["subindustry"])
    ]
    df["statement_type"] = df["report_type"]
    df["item_code"] = df["line_item_key"]
    df["parent_item_code"] = df["parent_line_item_key"]
    df = _filter_gold_features(df)
    if df.empty:
        for col in GOLD_REPORT_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return Output(
            df[GOLD_REPORT_COLUMNS],
            metadata={"num_records": 0},
        )

    df = df.drop(
        columns=[
            "standard_name",
            "level_1",
            "level_2",
            "level_3",
            "display_label",
            "sign_rule",
            "mapping_source",
        ],
        errors="ignore",
    )
    classification = df.apply(_classify_line, axis=1)
    df = pd.concat([df, classification], axis=1)
    df = _add_hierarchy_metadata(df)

    for col in GOLD_REPORT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[GOLD_REPORT_COLUMNS].sort_values(
        ["ticker", "statement_type", "year", "quarter", "display_order"]
    )
    
    return Output(
        df,
        metadata={"num_records": len(df)},
    )

@asset(
    partitions_def=report_partitions,
    ins={
        "gold_reports": AssetIn(
            key_prefix=["gold"]
        )
    },
    io_manager_key="psql_io_manager",
    key_prefix=["warehouse"],
    compute_kind="python",
    group_name="warehouse",
)
def warehouse_reports (gold_reports: pd.DataFrame,
) -> Output[pd.DataFrame]:

    return Output(
        gold_reports,
        metadata={
            "table": "warehouse.warehouse_reports",
            "rows_loaded": len(gold_reports),
            "unique_key": [
                "ticker", "year", "quarter", "report_type", "line_item_key"
            ],
            "replace_by_columns": ["year", "quarter"],
        },
    )
