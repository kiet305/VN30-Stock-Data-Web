import re
import unicodedata

import numpy as np
import pandas as pd


REPORT_TYPE_LABELS = {
    "BS": "Balance sheet",
    "IS": "Income statement",
    "CF": "Cash flow",
}

REPORT_TYPE_ALIASES = {
    "bs": "BS",
    "balance_sheet": "BS",
    "is": "IS",
    "income_statement": "IS",
    "cf": "CF",
    "cash_flow": "CF",
}

DETAIL_COLUMNS = [
    "ticker",
    "year",
    "quarter",
    "period_label",
    "report_type",
    "report_name",
    "criteria",
    "line_item_key",
    "item_id",
    "item_name_vi",
    "item_name_en",
    "value",
    "raw_value",
    "display_order",
    "level",
    "parent_item_id",
    "parent_line_item_key",
    "is_total",
    "is_leaf",
    "unit",
    "source",
    "date_fetched",
]

DIMENSION_CANDIDATES = {
    "ticker": ["ticker", "CP", "symbol"],
    "year": ["year", "Nam", "Năm", "NÄƒm", "NÃ„Æ’m"],
    "quarter": ["quarter", "Ky", "Kỳ", "Ká»³", "KÃ¡Â»Â³"],
}

EXCLUDED_VALUE_COLUMNS = {
    "ticker",
    "CP",
    "symbol",
    "year",
    "Nam",
    "Năm",
    "NÄƒm",
    "NÃ„Æ’m",
    "quarter",
    "Ky",
    "Kỳ",
    "Ká»³",
    "KÃ¡Â»Â³",
    "report_type",
    "source",
    "period_type",
    "period_label",
    "date_fetched",
    "_partition_key",
}

TOTAL_KEYWORDS = (
    "tong",
    "loi nhuan",
    "lai thuan",
    "luu chuyen tien thuan",
    "von chu so huu",
    "no phai tra",
    "tai san",
    "nguon von",
)

LEGACY_CRITERIA_ALIASES = {
    "doanh thu thuan": "revenue",
    "doanh thu": "revenue",
    "tong thu nhap hoat dong": "revenue",
    "thu nhap lai va cac khoan thu nhap tuong tu": "interest_income",
    "chi phi lai va cac chi phi tuong tu": "interest_expenses",
    "loi nhuan sau thue": "profit",
    "loi nhuan sau thue ngan hang me": "profit",
    "loi nhuan sau thue cua co dong cong ty me": "parent_profit",
    "net profit loss after tax": "profit",
    "tong cong tai san": "total_assets",
    "total assets": "total_assets",
    "no phai tra": "liabilities",
    "tong no phai tra": "liabilities",
    "von chu so huu": "equity",
    "total owner s equity": "equity",
    "owners equity": "equity",
    "tien gui tai ngan hang nha nuoc viet nam": "deposit_at_SBV",
    "balances with the sbv": "deposit_at_SBV",
    "tien gui va cho vay cac tctd khac": "deposit_at_FI",
    "tien gui tai cac tctd khac va cho vay cac tctd khac": "deposit_at_FI",
    "placements with and loans to other credit institutions": "deposit_at_FI",
    "chung khoan dau tu": "investment_securities",
    "investment securities": "investment_securities",
    "cho vay khach hang": "customer_loan",
    "loans to customers": "customer_loan",
}

CRITERIA_ALIASES = {
    "net_profit_loss_after_tax": "profit",
    "attributable_to_parent_company": "parent_profit",
    "profit_after_tax": "profit",
    "net_profit_loss_after_tax_for_shareholders_of_parent_company": "parent_profit",
    "profit_after_tax_for_shareholders_of_parent_company": "parent_profit",
    "owners_equity": "equity",
    "owner_s_equity": "equity",
    "total_owner_s_equity": "equity",
    "total_equity": "equity",
    "total_assets": "total_assets",
    "long_term_assets": "non_current_assets",
    "short_term_receivables": "accounts_receivable",
    "inventories_net": "inventory",
    "investment_properties": "investment_property",
    "long_term_liabilities": "non_current_liabilities",
    "total_resource": "total_liabilities_and_equity",
    "undistributed_earnings": "retained_earnings",
    "minority_interests": "minority_interest",
    "total_liabilities": "liabilities",
    "total_operating_income": "revenue",
    "revenue": "revenue",
    "net_revenue": "revenue",
    "net_sales": "revenue",
    "cost_of_sales": "cost_of_goods_sold",
    "cogs": "cost_of_goods_sold",
    "sales_expenses": "selling_expenses",
    "general_and_admin_expenses": "general_admin_expenses",
    "admin_expenses": "general_admin_expenses",
    "operating_profit_loss": "operating_profit",
    "net_other_income_expenses": "other_profit",
    "income_from_investments_in_other_entities": "associates_profit_loss",
    "gain_loss_from_joint_ventures_from_2015": "associates_profit_loss",
    "net_accounting_profit_loss_before_tax": "profit_before_tax",
    "business_income_tax_current": "current_income_tax_expense",
    "business_income_tax_deferred": "deferred_income_tax_expense",
    "business_income_tax_expenses": "current_income_tax_expense",
    "corporate_income_tax_expenses": "current_income_tax_expense",
    "eps_basic_vnd": "basic_eps",
    "net_cash_inflows_outflows_from_operating_activities": "cashflow_operating",
    "net_cash_from_operating_activities": "cashflow_operating",
    "net_cash_flows_from_operating_activities_before_cit": "cashflow_operating",
    "net_cash_inflows_outflows_from_investing_activities": "cashflow_investing",
    "net_cash_from_investing_activities": "cashflow_investing",
    "net_cash_inflows_outflows_from_financing_activities": "cashflow_financing",
    "net_cash_from_financing_activities": "cashflow_financing",
    "net_increase_in_cash_and_cash_equivalents": "net_cashflow",
    "net_increase_decrease_in_cash_and_cash_equivalents": "net_cashflow",
    "cash_and_cash_equivalents_at_the_beginning_of_period": "cash_beginning",
    "cash_and_bank_deposit_at_the_beginning_of_the_period": "cash_beginning",
    "cash_and_cash_equivalents_at_the_end_of_period": "cash_ending",
    "cash_and_cash_equivalents_at_end_of_the_period": "cash_ending",
    "interest_and_similar_income": "interest_income",
    "interest_and_similar_expenses": "interest_expenses",
    "balances_with_the_sbv": "deposit_at_SBV",
    "balances_with_state_bank_of_vietnam": "deposit_at_SBV",
    "placements_with_and_loans_to_other_credit_institutions": "deposit_at_FI",
    "deposits_with_and_loans_to_other_credit_institutions": "deposit_at_FI",
    "investment_securities": "investment_securities",
    "securities_investments": "investment_securities",
    "loans_and_advances_to_customers_net": "customer_loan",
    "loans_to_customers": "customer_loan",
}

LEGACY_BS_MAPPINGS = {
    # Non-financial balance sheet
    "tai san ngan han": ("current_assets", "TÀI SẢN NGẮN HẠN", "Current assets", 1000, 1),
    "tien va tuong duong tien": ("cash_and_equivalents", "Tiền và tương đương tiền", "Cash and cash equivalents", 1010, 2),
    "gia tri thuan dau tu ngan han": ("short_term_investments", "Giá trị thuần đầu tư ngắn hạn", "Short-term investments", 1020, 2),
    "cac khoan phai thu ngan han": ("short_term_receivables", "Các khoản phải thu ngắn hạn", "Short-term receivables", 1030, 2),
    "tra truoc cho nguoi ban ngan han": ("short_term_supplier_prepayments", "Trả trước cho người bán ngắn hạn", "Short-term supplier prepayments", 1031, 2),
    "phai thu ve cho vay ngan han": ("short_term_loan_receivables", "Phải thu về cho vay ngắn hạn", "Short-term loan receivables", 1032, 2),
    "hang ton kho rong": ("inventory", "Hàng tồn kho ròng", "Inventories", 1040, 2),
    "hang ton kho": ("inventory", "Hàng tồn kho, ròng", "Inventories", 1040, 2),
    "tai san luu dong khac": ("other_current_assets", "Tài sản lưu động khác", "Other current assets", 1050, 2),
    "tai san dai han": ("non_current_assets", "TÀI SẢN DÀI HẠN", "Non-current assets", 1100, 1),
    "phai thu ve cho vay dai han": ("long_term_loan_receivables", "Phải thu về cho vay dài hạn", "Long-term loan receivables", 1110, 2),
    "phai thu dai han": ("long_term_receivables", "Phải thu dài hạn", "Long-term receivables", 1111, 2),
    "phai thu dai han khac": ("other_long_term_receivables", "Phải thu dài hạn khác", "Other long-term receivables", 1112, 2),
    "tai san co dinh": ("fixed_assets", "Tài sản cố định", "Fixed assets", 1120, 2),
    "gia tri rong tai san dau tu": ("investment_property", "Giá trị ròng tài sản đầu tư", "Investment property", 1130, 2),
    "dau tu dai han": ("long_term_investments", "Đầu tư dài hạn", "Long-term investments", 1140, 2),
    "tai san dai han khac": ("other_non_current_assets", "Tài sản dài hạn khác", "Other non-current assets", 1150, 2),
    "tra truoc dai han": ("long_term_prepayments", "Trả trước dài hạn", "Long-term prepayments", 1151, 2),
    "loi the thuong mai": ("goodwill", "Lợi thế thương mại", "Goodwill", 1152, 2),
    "tong cong tai san": ("total_assets", "TỔNG CỘNG TÀI SẢN", "Total assets", 1190, 0),
    "no phai tra": ("liabilities", "NỢ PHẢI TRẢ", "Liabilities", 1200, 1),
    "no ngan han": ("current_liabilities", "Nợ ngắn hạn", "Current liabilities", 1210, 2),
    "nguoi mua tra tien truoc ngan han": ("short_term_customer_prepayments", "Người mua trả tiền trước ngắn hạn", "Short-term customer prepayments", 1211, 2),
    "vay va no thue tai chinh ngan han": ("short_term_borrowings", "Vay và nợ thuê tài chính ngắn hạn", "Short-term borrowings", 1212, 2),
    "trai phieu chuyen doi": ("convertible_bonds", "Trái phiếu chuyển đổi", "Convertible bonds", 1213, 2),
    "no dai han": ("non_current_liabilities", "Nợ dài hạn", "Non-current liabilities", 1220, 2),
    "vay va no thue tai chinh dai han": ("long_term_borrowings", "Vay và nợ thuê tài chính dài hạn", "Long-term borrowings", 1221, 2),
    "von chu so huu": ("equity", "VỐN CHỦ SỞ HỮU", "Owners' equity", 1300, 1),
    "von va cac quy": ("capital_and_reserves", "Vốn và các quỹ", "Capital and reserves", 1310, 2),
    "von gop cua chu so huu": ("paid_in_capital", "Vốn góp của chủ sở hữu", "Paid-in capital", 1311, 2),
    "co phieu pho thong": ("ordinary_shares", "Cổ phiếu phổ thông", "Ordinary shares", 1312, 2),
    "quy dau tu va phat trien": ("development_investment_fund", "Quỹ đầu tư và phát triển", "Development investment fund", 1313, 2),
    "cac quy khac": ("other_reserves", "Các quỹ khác", "Other reserves", 1320, 2),
    "lai chua phan phoi": ("retained_earnings", "Lãi chưa phân phối", "Retained earnings", 1330, 2),
    "loi ich cua co dong thieu so": ("minority_interest", "LỢI ÍCH CỦA CỔ ĐÔNG THIỂU SỐ", "Minority interest", 1340, 2),
    "tong cong nguon von": ("total_liabilities_and_equity", "TỔNG CỘNG NGUỒN VỐN", "Total liabilities and equity", 1390, 0),

    # Bank balance sheet
    "tien gui tai ngan hang nha nuoc viet nam": ("deposit_at_SBV", "Tiền gửi tại Ngân hàng Nhà nước Việt Nam", "Balances with the SBV", 2000, 1),
    "tien gui tai cac tctd khac va cho vay cac tctd khac": ("deposit_at_FI", "Tiền gửi tại các TCTD khác và cho vay các TCTD khác", "Placements with and loans to other credit institutions", 2010, 1),
    "chung khoan kinh doanh": ("trading_securities", "Chứng khoán kinh doanh", "Trading securities", 2020, 1),
    "_chung khoan kinh doanh": ("trading_securities_gross", "Chứng khoán kinh doanh - giá trị gốc", "Trading securities - gross", 2021, 2),
    "du phong giam gia chung khoan kinh doanh": ("trading_securities_provision", "Dự phòng giảm giá chứng khoán kinh doanh", "Trading securities provision", 2022, 2),
    "cac cong cu tai chinh phai sinh va khoan no tai chinh khac": ("derivatives_and_other_financial_assets", "Các công cụ tài chính phái sinh và tài sản tài chính khác", "Derivatives and other financial assets", 2030, 1),
    "_cac cong cu tai chinh phai sinh va khoan no tai chinh khac": ("derivatives_and_other_financial_liabilities", "Các công cụ tài chính phái sinh và nợ tài chính khác", "Derivatives and other financial liabilities", 2210, 1),
    "cho vay khach hang": ("customer_loan", "Cho vay khách hàng", "Loans to customers", 2040, 1),
    "_cho vay khach hang": ("customer_loan_gross", "Cho vay khách hàng - dư nợ gốc", "Loans to customers - gross", 2041, 2),
    "du phong rui ro cho vay khach hang": ("customer_loan_provision", "Dự phòng rủi ro cho vay khách hàng", "Loan loss provision", 2042, 2),
    "chung khoan dau tu": ("investment_securities", "Chứng khoán đầu tư", "Investment securities", 2050, 1),
    "chung khoan dau tu san sang de ban": ("available_for_sale_securities", "Chứng khoán đầu tư sẵn sàng để bán", "Available-for-sale securities", 2051, 2),
    "chung khoan dau tu giu den ngay dao han": ("held_to_maturity_securities", "Chứng khoán đầu tư giữ đến ngày đáo hạn", "Held-to-maturity securities", 2052, 2),
    "du phong giam gia chung khoan dau tu": ("investment_securities_provision", "Dự phòng giảm giá chứng khoán đầu tư", "Investment securities provision", 2053, 2),
    "dau tu vao cong ty lien doanh": ("investment_in_associates", "Đầu tư vào công ty liên doanh", "Investments in associates", 2060, 1),
    "dau tu vao cong ty con": ("investment_in_subsidiaries", "Đầu tư vào công ty con", "Investments in subsidiaries", 2061, 1),
    "du phong giam gia dau tu dai han": ("long_term_investment_provision", "Dự phòng giảm giá đầu tư dài hạn", "Long-term investment provision", 2062, 2),
    "tai san co dinh huu hinh": ("tangible_fixed_assets", "Tài sản cố định hữu hình", "Tangible fixed assets", 2070, 1),
    "tai san co dinh vo hinh": ("intangible_fixed_assets", "Tài sản cố định vô hình", "Intangible fixed assets", 2071, 1),
    "tai san co dinh thue tai chinh": ("finance_lease_fixed_assets", "Tài sản cố định thuê tài chính", "Finance lease fixed assets", 2072, 1),
    "tai san co khac": ("other_assets", "Tài sản Có khác", "Other assets", 2080, 1),
    "cac khoan no chinh phu va nhnn viet nam": ("debt_at_SBV_and_government", "Các khoản nợ Chính phủ và NHNN Việt Nam", "Borrowings from Government and the SBV", 2200, 1),
    "tien gui va vay cac to chuc tin dung khac": ("debt_at_FI", "Tiền gửi và vay các Tổ chức tín dụng khác", "Deposits and borrowings from other credit institutions", 2220, 1),
    "tien gui cua khach hang": ("customer_deposit", "Tiền gửi của khách hàng", "Customer deposits", 2230, 1),
    "von tai tro uy thac dau tu cua cp va cac to chuc td khac": ("entrusted_investment_funds", "Vốn tài trợ, uỷ thác đầu tư của CP và các tổ chức TD khác", "Entrusted investment funds", 2240, 1),
    "phat hanh giay to co gia": ("valuable_papers_issued", "Phát hành giấy tờ có giá", "Valuable papers issued", 2250, 1),
    "cac khoan no khac": ("other_liabilities", "Các khoản nợ khác", "Other liabilities", 2260, 1),
    "von cua to chuc tin dung": ("credit_institution_capital", "Vốn của tổ chức tín dụng", "Credit institution capital", 2300, 1),
    "quy cua to chuc tin dung": ("credit_institution_reserves", "Quỹ của tổ chức tín dụng", "Credit institution reserves", 2310, 1),
    "chenh lech ty gia hoi doai": ("foreign_exchange_difference", "Chênh lệch tỷ giá hối đoái", "Foreign exchange difference", 2320, 1),
    "chenh lech danh gia lai tai san": ("asset_revaluation_difference", "Chênh lệch đánh giá lại tài sản", "Asset revaluation difference", 2321, 1),
    "von ngan sach nha nuoc va quy khac": ("state_budget_and_other_funds", "Vốn Ngân sách nhà nước và quỹ khác", "State budget and other funds", 2330, 1),
    "_cac quy khac": ("bank_other_reserves", "Các quỹ khác", "Other bank reserves", 2331, 1),
    "co dong thieu so": ("minority_interest", "Cổ đông thiểu số", "Minority interest", 2340, 1),
}

LEGACY_IS_MAPPINGS = {
    "doanh thu thuan": ("revenue", "Doanh thu thuần", "Net revenue", 1000, 1),
    "doanh thu": ("revenue", "Doanh thu", "Revenue", 1000, 1),
    "gia von hang ban": ("cost_of_goods_sold", "Giá vốn hàng bán", "Cost of goods sold", 1010, 1),
    "loi nhuan gop": ("gross_profit", "Lợi nhuận gộp", "Gross profit", 1020, 1),
    "doanh thu hoat dong tai chinh": ("financial_income", "Doanh thu hoạt động tài chính", "Financial income", 1030, 1),
    "chi phi tai chinh": ("financial_expenses", "Chi phí tài chính", "Financial expenses", 1040, 1),
    "chi phi lai vay": ("interest_expenses", "Chi phí lãi vay", "Interest expenses", 1041, 2),
    "chi phi ban hang": ("selling_expenses", "Chi phí bán hàng", "Selling expenses", 1050, 1),
    "chi phi quan ly doanh nghiep": ("general_admin_expenses", "Chi phí quản lý doanh nghiệp", "General and admin expenses", 1060, 1),
    "loi nhuan thuan tu hoat dong kinh doanh": ("operating_profit", "Lợi nhuận thuần từ hoạt động kinh doanh", "Operating profit", 1070, 1),
    "loi nhuan khac": ("other_profit", "Lợi nhuận khác", "Other profit", 1080, 1),
    "tong loi nhuan ke toan truoc thue": ("profit_before_tax", "Tổng lợi nhuận kế toán trước thuế", "Profit before tax", 1090, 1),
    "loi nhuan truoc thue": ("profit_before_tax", "Lợi nhuận trước thuế", "Profit before tax", 1090, 1),
    "chi phi thue tndn hien hanh": ("current_income_tax_expense", "Chi phí thuế TNDN hiện hành", "Current income tax expense", 1100, 2),
    "chi phi thue tndn hoan lai": ("deferred_income_tax_expense", "Chi phí thuế TNDN hoãn lại", "Deferred income tax expense", 1110, 2),
    "loi nhuan sau thue": ("profit", "Lợi nhuận sau thuế", "Profit after tax", 1120, 1),
    "loi nhuan sau thue cua co dong cong ty me": ("parent_profit", "Lợi nhuận sau thuế của cổ đông công ty mẹ", "Profit attributable to parent company", 1121, 1),
    "loi nhuan sau thue ngan hang me": ("profit", "Lợi nhuận sau thuế Ngân hàng mẹ", "Profit attributable to parent bank", 1121, 1),
    "thu nhap lai va cac khoan thu nhap tuong tu": ("interest_income", "Thu nhập lãi và các khoản thu nhập tương tự", "Interest and similar income", 2000, 2),
    "chi phi lai va cac chi phi tuong tu": ("interest_expenses", "Chi phí lãi và các chi phí tương tự", "Interest and similar expenses", 2010, 2),
    "thu nhap lai thuan": ("net_interest_income", "Thu nhập lãi thuần", "Net interest income", 2020, 1),
    "lai thuan tu hoat dong dich vu": ("net_service_income", "Lãi thuần từ hoạt động dịch vụ", "Net service income", 2030, 1),
    "lai lo thuan tu hoat dong kinh doanh ngoai hoi": ("net_foreign_exchange_income", "Lãi/(lỗ) thuần từ hoạt động kinh doanh ngoại hối", "Net foreign exchange income", 2040, 1),
    "lai lo thuan tu mua ban chung khoan kinh doanh": ("net_trading_securities_income", "Lãi/(lỗ) thuần từ mua bán chứng khoán kinh doanh", "Net trading securities income", 2050, 1),
    "lai lo thuan tu mua ban chung khoan dau tu": ("net_investment_securities_income", "Lãi/(lỗ) thuần từ mua bán chứng khoán đầu tư", "Net investment securities income", 2060, 1),
    "thu nhap tu gop von mua co phan": ("dividend_income", "Thu nhập từ góp vốn, mua cổ phần", "Dividend income", 2070, 1),
    "lai lo tu cong ty lien doanh": ("associates_profit_loss", "Lãi/(lỗ) từ công ty liên doanh", "Gain/(loss) from joint ventures", 1085, 1),
    "lai lo trong cong ty lien doanh lien ket": ("associates_profit_loss", "Lãi/lỗ trong công ty liên doanh, liên kết", "Gain/(loss) from associates and joint ventures", 1085, 1),
    "lai co ban tren co phieu": ("basic_eps", "Lãi cơ bản trên cổ phiếu", "Basic EPS", 1130, 1),
    "tong thu nhap hoat dong": ("revenue", "Tổng thu nhập hoạt động", "Total operating income", 2080, 1),
    "chi phi hoat dong": ("operating_expenses", "Chi phí hoạt động", "Operating expenses", 2090, 1),
    "chi phi du phong rui ro tin dung": ("credit_provision_expense", "Chi phí dự phòng rủi ro tín dụng", "Credit provision expense", 2100, 1),
}

LEGACY_CF_MAPPINGS = {
    "luu chuyen tien te tu hoat dong kinh doanh": ("cashflow_operating", "Lưu chuyển tiền tệ từ hoạt động kinh doanh", "Cash flows from operating activities", 1000, 1),
    "luu chuyen tien thuan tu hoat dong kinh doanh": ("cashflow_operating", "Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Net cash flows from operating activities", 1000, 1),
    "luu chuyen tien te tu hoat dong dau tu": ("cashflow_investing", "Lưu chuyển tiền tệ từ hoạt động đầu tư", "Cash flows from investing activities", 2000, 1),
    "luu chuyen tien thuan tu hoat dong dau tu": ("cashflow_investing", "Lưu chuyển tiền thuần từ hoạt động đầu tư", "Net cash flows from investing activities", 2000, 1),
    "luu chuyen tien te tu hoat dong tai chinh": ("cashflow_financing", "Lưu chuyển tiền tệ từ hoạt động tài chính", "Cash flows from financing activities", 3000, 1),
    "luu chuyen tien thuan tu hoat dong tai chinh": ("cashflow_financing", "Lưu chuyển tiền thuần từ hoạt động tài chính", "Net cash flows from financing activities", 3000, 1),
    "luu chuyen tien thuan trong ky": ("net_cashflow", "Lưu chuyển tiền thuần trong kỳ", "Net cash flows during the period", 4000, 1),
    "tien va tuong duong tien dau ky": ("cash_beginning", "Tiền và tương đương tiền đầu kỳ", "Cash and cash equivalents at beginning of period", 5000, 1),
    "tien va tuong duong tien cuoi ky": ("cash_ending", "Tiền và tương đương tiền cuối kỳ", "Cash and cash equivalents at end of period", 6000, 1),
}

LEGACY_REPORT_MAPPINGS = {
    "BS": LEGACY_BS_MAPPINGS,
    "IS": LEGACY_IS_MAPPINGS,
    "CF": LEGACY_CF_MAPPINGS,
}

VCI_BS_STRUCTURE = {
    "current_assets": (0, 1000),
    "cash_and_cash_equivalents": (1, 1010),
    "cash": (2, 1011),
    "cash_equivalents": (2, 1012),
    "short_term_investments": (1, 1020),
    "held_to_maturity_investment": (2, 1021),
    "government_bonds_purchased_for_resale": (2, 1022),
    "provision_for_diminution": (2, 1023),
    "accounts_receivable": (1, 1030),
    "trade_accounts_receivable": (2, 1031),
    "prepayments_to_suppliers": (2, 1032),
    "intercompany_receivables": (2, 1033),
    "construction_contract_in_progress_receivables": (2, 1034),
    "other_receivables": (2, 1035),
    "provision_for_doubtful_debts": (2, 1036),
    "short_term_loans_receivables": (2, 1037),
    "inventories_net": (1, 1040),
    "inventories": (2, 1041),
    "provision_for_decline_in_inventories": (2, 1042),
    "other_current_assets": (1, 1050),
    "short_term_prepayments": (2, 1051),
    "vat_to_be_claimed": (2, 1052),
    "other_taxes_receivable": (2, 1053),
    "shortage_of_current_assets_waiting_for_solution": (2, 1054),
    "short_term_unrealized_revenue": (2, 1055),
    "long_term_assets": (0, 2000),
    "long_term_trade_receivables": (1, 2010),
    "long_term_trade_receivables_from_customers": (2, 2011),
    "long_term_intercompany_receivables": (2, 2012),
    "other_long_term_receivables": (2, 2013),
    "provision_for_doubtful_lt_receivable": (2, 2014),
    "long_term_loans_receivables": (2, 2015),
    "long_term_prepayments_to_suppliers": (2, 2016),
    "fixed_assets": (1, 2020),
    "tangible_fixed_assets": (2, 2021),
    "finance_lease_assets": (2, 2024),
    "intangible_fixed_assets": (2, 2027),
    "construction_in_progress_before_2015": (2, 2030),
    "construction_in_progress": (2, 2031),
    "investment_properties": (1, 2040),
    "long_term_investments": (1, 2050),
    "investments_in_subsidiaries": (2, 2051),
    "investments_in_associates": (2, 2052),
    "other_long_term_investments": (2, 2053),
    "provision_for_long_term_investments": (2, 2054),
    "goodwill_before_2015": (1, 2060),
    "goodwill": (1, 2061),
    "other_long_term_assets": (1, 2070),
    "long_term_prepayments": (2, 2071),
    "deferred_income_tax_assets": (2, 2072),
    "long_term_incomplete_assets": (2, 2073),
    "long_term_cost_of_work_in_progress": (2, 2074),
    "long_term_equipment_material_and_spare_parts": (2, 2075),
    "total_assets": (0, 3000),
    "liabilities": (0, 4000),
    "current_liabilities": (1, 4010),
    "short_term_borrowings": (2, 4011),
    "trade_accounts_payable": (2, 4012),
    "advances_from_customers": (2, 4013),
    "taxes_and_other_payable_to_state_budget": (2, 4014),
    "payable_to_employees": (2, 4015),
    "accrued_expenses": (2, 4016),
    "intercompany_payables": (2, 4017),
    "construction_contract_in_progress_payables": (2, 4018),
    "other_payables": (2, 4019),
    "provision_for_st_liabilities": (2, 4020),
    "bonus_and_welfare_funds": (2, 4021),
    "short_term_customer_prepayments": (2, 4022),
    "convertible_bonds": (2, 4023),
    "conversion_options_on_convertible_bonds": (2, 4024),
    "price_stabilization_fund": (2, 4025),
    "long_term_liabilities": (1, 4030),
    "long_term_trade_payables": (2, 4031),
    "long_term_intercompany_payables": (2, 4032),
    "other_long_term_payables": (2, 4033),
    "long_term_borrowings": (2, 4034),
    "deferred_income_tax_liabilities": (2, 4035),
    "provision_for_severance_allowances": (2, 4036),
    "provision_for_long_term_liabilities": (2, 4037),
    "deferred_revenue": (2, 4038),
    "technology_science_development_fund": (2, 4039),
    "long_term_advances_from_customers": (2, 4040),
    "long_term_accrued_expenses": (2, 4041),
    "intra_company_payables_for_operating_capital_received": (2, 4042),
    "owners_equity": (0, 5000),
    "capital_and_reserves": (1, 5010),
    "paid_in_capital": (2, 5011),
    "common_shares": (3, 5012),
    "preferred_shares": (3, 5013),
    "paid_in_capital_in_wholly_owned_subsidiaries": (3, 5014),
    "share_premium": (2, 5015),
    "owners_other_capital": (2, 5016),
    "treasury_shares": (2, 5017),
    "differences_upon_asset_revaluation": (2, 5018),
    "foreign_exchange_differences": (2, 5019),
    "investment_and_development_funds": (2, 5020),
    "financial_reserve_funds": (2, 5021),
    "other_funds": (2, 5022),
    "undistributed_earnings": (2, 5023),
    "beginning_accumulated_undistributed_earnings": (3, 5024),
    "current_period_undistributed_earnings": (3, 5025),
    "enterprise_arrangement_fund": (2, 5026),
    "budget_sources_and_other_funds": (2, 5027),
    "bonus_and_welfare_funds_before_2010": (2, 5028),
    "minority_interests_before_2015": (2, 5029),
    "minority_interests": (2, 5030),
    "funds_used_for_fixed_asset_acquisitions": (2, 5031),
    "total_resource": (0, 6000),
}


def _empty_detail_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _canonical_report_type(report_type: str) -> str:
    key = str(report_type).strip().lower()
    return REPORT_TYPE_ALIASES.get(key, key.upper())


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    fallback = None
    for col in candidates:
        if col in df.columns:
            if fallback is None:
                fallback = col
            if not df[col].isna().all():
                return col
    return fallback


def _ascii_key(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: object) -> str:
    key = _ascii_key(value)
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_") or "line_item"


def _strip_numbering(label: object) -> str:
    text = "" if pd.isna(label) else str(label).strip()
    return re.sub(
        r"^\s*(?:[A-Z]\.|[IVXLCDM]+\.\s*|\d+[\.)]\s*)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _strip_legacy_unit(label: object) -> str:
    text = "" if pd.isna(label) else str(label).strip()
    text = re.sub(r"\s*\((?:đồng|dong|vnd)\)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _legacy_column_key(label: object) -> str:
    text = "" if pd.isna(label) else str(label).strip()
    has_leading_underscore = text.startswith("_")
    text = text.lstrip("_")
    key = _ascii_key(_strip_legacy_unit(text))
    return f"_{key}" if has_leading_underscore else key


def _legacy_line_metadata(
    column_name: object,
    report_type: str,
    fallback_order: int,
) -> dict[str, object]:
    key = _legacy_column_key(column_name)
    mapping = LEGACY_REPORT_MAPPINGS.get(report_type, {}).get(key)

    if mapping is None:
        clean_label = _strip_legacy_unit(str(column_name).lstrip("_"))
        criteria = _criteria_from_label(clean_label)
        return {
            "source_column": column_name,
            "criteria": criteria,
            "item_id": criteria,
            "item_name_vi": clean_label,
            "item_name_en": None,
            "display_order": 9000 + fallback_order,
            "level": _infer_level(clean_label),
            "is_total": _is_total_line(clean_label, _infer_level(clean_label)),
        }

    criteria, item_name_vi, item_name_en, display_order, level = mapping
    return {
        "source_column": column_name,
        "criteria": criteria,
        "item_id": criteria,
        "item_name_vi": item_name_vi,
        "item_name_en": item_name_en,
        "display_order": display_order,
        "level": level,
        "is_total": _is_total_line(item_name_vi, level),
    }


def _infer_level(label: object) -> int:
    text = "" if pd.isna(label) else str(label).strip()
    if re.match(r"^[A-H]\.\s+", text):
        return 0
    if re.match(r"^[IVXLCDM]+\.\s+", text, flags=re.IGNORECASE):
        return 1
    if re.match(r"^\d+[\.)]\s+", text):
        return 2
    return 1


def _is_total_line(label: object, level: int) -> bool:
    key = _ascii_key(label)
    return level <= 1 or any(keyword in key for keyword in TOTAL_KEYWORDS)


def _criteria_from_label(label: object) -> str:
    key = _ascii_key(_strip_numbering(label))
    return LEGACY_CRITERIA_ALIASES.get(key, _slug(label))


def _canonical_criteria(value: object) -> str:
    raw = "" if pd.isna(value) else str(value).strip()
    slug = _slug(raw)
    return CRITERIA_ALIASES.get(raw, CRITERIA_ALIASES.get(slug, raw or slug))


def _vci_bs_structure(item_id: object, item_name: object, fallback_order: int) -> tuple[int, int]:
    item_id = "" if pd.isna(item_id) else str(item_id)
    name_key = _ascii_key(item_name)

    if item_id == "cost":
        if "huu hinh" in name_key:
            return 3, 2022
        if "thue tai chinh" in name_key:
            return 3, 2025
        if "vo hinh" in name_key:
            return 3, 2028
        if "tai san dau tu" in name_key:
            return 2, 2041
    if item_id == "accumulated_depreciation":
        if "huu hinh" in name_key:
            return 3, 2023
        if "thue tai chinh" in name_key:
            return 3, 2026
        if "vo hinh" in name_key:
            return 3, 2029
        if "tai san dau tu" in name_key:
            return 2, 2042
    if item_id == "other_long_term_assets" and name_key.startswith("cac "):
        return 2, 2076

    return VCI_BS_STRUCTURE.get(item_id, (1, 9000 + fallback_order))


def _deduplicate_vci_lines(out: pd.DataFrame) -> pd.DataFrame:
    key_cols = [
        "ticker", "year", "quarter", "report_type",
        "item_id", "_item_name_key",
    ]
    required_cols = [
        "ticker", "year", "quarter", "report_type",
        "item_id", "item_name_vi",
    ]
    if not set(required_cols).issubset(out.columns):
        return out

    src = out.copy()
    src["_item_name_key"] = src["item_name_vi"].map(_ascii_key)
    src["_abs_raw_value"] = src["raw_value"].abs().fillna(0)
    src = src.sort_values(key_cols + ["_abs_raw_value"], ascending=[True] * len(key_cols) + [False])
    src = src.drop_duplicates(subset=key_cols, keep="first")
    return src.drop(columns=["_item_name_key", "_abs_raw_value"])


def _apply_vci_long_structure(out: pd.DataFrame, report_type: str) -> pd.DataFrame:
    if out.empty or report_type != "BS":
        return out

    out = out.copy()
    structure = [
        _vci_bs_structure(item_id, item_name, int(order))
        for item_id, item_name, order in zip(
            out["item_id"],
            out["item_name_vi"],
            out["display_order"],
        )
    ]
    out["level"] = [level for level, _ in structure]
    out["display_order"] = [order for _, order in structure]
    out["is_total"] = [
        _is_total_line(label, level)
        for label, level in zip(out["item_name_vi"], out["level"])
    ]
    return out


def _value_to_billions(value: pd.Series) -> pd.Series:
    raw = pd.to_numeric(value, errors="coerce")
    return (raw / 1_000_000_000).round(3)


def _period_label(year: pd.Series, quarter: pd.Series) -> pd.Series:
    return year.astype(int).astype(str) + "-Q" + quarter.astype(int).astype(str)


def _line_dimension(out: pd.DataFrame) -> pd.DataFrame:
    dim = (
        out[
            [
                "report_type",
                "criteria",
                "item_id",
                "item_name_vi",
                "display_order",
                "level",
                "is_total",
            ]
        ]
        .drop_duplicates()
        .sort_values(["report_type", "display_order", "criteria"])
        .copy()
    )

    duplicate_no = dim.groupby(["report_type", "criteria"]).cumcount()
    dim["line_item_key"] = dim["criteria"].where(
        duplicate_no.eq(0),
        dim["criteria"] + "__" + duplicate_no.astype(str),
    )

    parent_frames = []
    for _, report_dim in dim.groupby("report_type", sort=False):
        report_dim = report_dim.copy()
        parent_stack: dict[str, str] = {}
        parent_keys = []
        for _, row in report_dim.iterrows():
            level = int(row["level"])
            parent_keys.append(parent_stack.get(str(level - 1)))
            parent_stack[str(level)] = row["line_item_key"]
            for old_level in list(parent_stack):
                if int(old_level) > level:
                    parent_stack.pop(old_level, None)

        report_dim["parent_line_item_key"] = parent_keys
        parent_frames.append(report_dim)

    dim = pd.concat(parent_frames, ignore_index=True)
    dim["parent_item_id"] = dim["parent_line_item_key"]
    parent_set = set(dim["parent_line_item_key"].dropna())
    dim["is_leaf"] = ~dim["line_item_key"].isin(parent_set)
    return dim[
        [
            "report_type",
            "criteria",
            "item_id",
            "item_name_vi",
            "display_order",
            "line_item_key",
            "parent_item_id",
            "parent_line_item_key",
            "is_leaf",
        ]
    ]


def _finalize_detail_df(out: pd.DataFrame) -> pd.DataFrame:
    if out.empty:
        return _empty_detail_df()

    out = out.copy()
    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    out["quarter"] = pd.to_numeric(out["quarter"], errors="coerce")
    out = out.dropna(subset=["ticker", "year", "quarter", "criteria"]).copy()
    out["year"] = out["year"].astype(int)
    out["quarter"] = out["quarter"].astype(int)
    out["criteria"] = out["criteria"].map(_canonical_criteria)
    out["period_label"] = _period_label(out["year"], out["quarter"])
    out["report_name"] = out["report_type"].map(REPORT_TYPE_LABELS).fillna(
        out["report_type"]
    )

    line_dim = _line_dimension(out)
    out = out.merge(
        line_dim,
        on=["report_type", "criteria", "item_id", "item_name_vi", "display_order"],
        how="left",
    )

    out["unit"] = "billion_vnd"
    out["source"] = out.get("source", "unknown")

    for col in DETAIL_COLUMNS:
        if col not in out.columns:
            out[col] = None

    return out[DETAIL_COLUMNS].sort_values(
        ["ticker", "report_type", "year", "quarter", "display_order"]
    )


def _normalize_vci_long(df: pd.DataFrame, report_type: str) -> pd.DataFrame:
    out = df.copy()
    canonical_type = _canonical_report_type(report_type)

    ticker_col = _first_existing_column(out, DIMENSION_CANDIDATES["ticker"])
    year_col = _first_existing_column(out, DIMENSION_CANDIDATES["year"])
    quarter_col = _first_existing_column(out, DIMENSION_CANDIDATES["quarter"])
    if ticker_col is None or year_col is None or quarter_col is None:
        raise KeyError("Report data must include ticker/year/quarter columns")

    out["ticker"] = out[ticker_col]
    out["year"] = out[year_col]
    out["quarter"] = out[quarter_col]
    out["report_type"] = out.get("report_type", canonical_type)
    out["report_type"] = out["report_type"].map(_canonical_report_type)
    out["report_type"] = out["report_type"].fillna(canonical_type)

    out["item_id"] = out["item_id"].astype(str)
    out["criteria"] = out["item_id"].apply(_canonical_criteria)
    out["item_name_vi"] = out["item"].astype(str) if "item" in out.columns else out["item_id"]
    out["item_name_en"] = out["item_en"].astype(str) if "item_en" in out.columns else None

    value_col = "value_raw" if "value_raw" in out.columns else "value"
    out["raw_value"] = pd.to_numeric(out[value_col], errors="coerce")
    out["value"] = (out["raw_value"] / 1_000_000_000).round(3)
    out = _deduplicate_vci_lines(out)

    line_order = (
        out[["report_type", "item_id", "item_name_vi"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    line_order["display_order"] = line_order.groupby("report_type").cumcount()
    out = out.merge(
        line_order,
        on=["report_type", "item_id", "item_name_vi"],
        how="left",
    )
    out["display_order"] = out["display_order"].fillna(0).astype(int)
    out["level"] = out["item_name_vi"].apply(_infer_level)
    out["is_total"] = [
        _is_total_line(label, level)
        for label, level in zip(out["item_name_vi"], out["level"])
    ]
    out["source"] = out["source"] if "source" in out.columns else "VCI"
    out = _apply_vci_long_structure(out, canonical_type)

    return _finalize_detail_df(out)


def _normalize_legacy_wide(df: pd.DataFrame, report_type: str) -> pd.DataFrame:
    src = df.copy()
    canonical_type = _canonical_report_type(report_type)

    ticker_col = _first_existing_column(src, DIMENSION_CANDIDATES["ticker"])
    year_col = _first_existing_column(src, DIMENSION_CANDIDATES["year"])
    quarter_col = _first_existing_column(src, DIMENSION_CANDIDATES["quarter"])
    if ticker_col is None or year_col is None or quarter_col is None:
        raise KeyError("Legacy report data must include ticker/year/quarter columns")

    src["ticker"] = src[ticker_col]
    src["year"] = src[year_col]
    src["quarter"] = src[quarter_col]
    src["report_type"] = src.get("report_type", canonical_type)
    src["report_type"] = src["report_type"].map(_canonical_report_type)
    src["report_type"] = src["report_type"].fillna(canonical_type)

    value_cols = [
        col for col in src.columns
        if col not in EXCLUDED_VALUE_COLUMNS
        and pd.to_numeric(src[col], errors="coerce").notna().any()
    ]
    if not value_cols:
        return _empty_detail_df()

    metadata = pd.DataFrame(
        [
            _legacy_line_metadata(col, canonical_type, idx)
            for idx, col in enumerate(value_cols)
        ]
    )
    out = src.melt(
        id_vars=["ticker", "year", "quarter", "report_type"],
        value_vars=value_cols,
        var_name="source_column",
        value_name="raw_value",
    )
    out = out.dropna(subset=["raw_value"]).copy()
    out["raw_value"] = pd.to_numeric(out["raw_value"], errors="coerce")
    out = out.dropna(subset=["raw_value"]).copy()
    out["value"] = (out["raw_value"] / 1_000_000_000).round(3)
    out = out.merge(metadata, on="source_column", how="left")
    out["display_order"] = out["display_order"].fillna(9000).astype(int)
    out["level"] = out["level"].fillna(1).astype(int)
    out["is_total"] = out["is_total"].fillna(False).astype(bool)
    out["source"] = "legacy_wide"

    return _finalize_detail_df(out)


def normalize_reports(df: pd.DataFrame, report_type: str = "is") -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_detail_df()

    if {"item_id", "value_raw"}.issubset(df.columns):
        return _normalize_vci_long(df, report_type)

    return _normalize_legacy_wide(df, report_type)


def convert_fact_table(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_detail_df()

    for col in DETAIL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[DETAIL_COLUMNS].copy()
