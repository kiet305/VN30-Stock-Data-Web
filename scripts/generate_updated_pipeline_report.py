from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


ROOT = Path(r"D:\New folder\FinalProject")
OUTPUT = ROOT / "output" / "pdf" / "bao_cao_pipeline_cap_nhat.pdf"


def register_fonts() -> tuple[str, str, str]:
    fonts_dir = Path(r"C:\Windows\Fonts")
    regular = fonts_dir / "times.ttf"
    bold = fonts_dir / "timesbd.ttf"
    italic = fonts_dir / "timesi.ttf"
    if regular.exists() and bold.exists() and italic.exists():
        pdfmetrics.registerFont(TTFont("TimesNewRoman", regular))
        pdfmetrics.registerFont(TTFont("TimesNewRoman-Bold", bold))
        pdfmetrics.registerFont(TTFont("TimesNewRoman-Italic", italic))
        return "TimesNewRoman", "TimesNewRoman-Bold", "TimesNewRoman-Italic"
    return "Times-Roman", "Times-Bold", "Times-Italic"


FONT, FONT_BOLD, FONT_ITALIC = register_fonts()


def make_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=16,
            leading=20,
            spaceAfter=12,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubTitle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=12,
            leading=15,
            spaceBefore=8,
            spaceAfter=8,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="LayerTitle",
            parent=styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=11.5,
            leading=14,
            spaceBefore=10,
            spaceAfter=5,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["Normal"],
            fontName=FONT,
            fontSize=10.5,
            leading=13.4,
            firstLineIndent=14,
            alignment=TA_JUSTIFY,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyNoIndent",
            parent=styles["Body"],
            firstLineIndent=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Bullet",
            parent=styles["BodyNoIndent"],
            leftIndent=14,
            firstLineIndent=0,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Caption",
            parent=styles["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=12,
            alignment=TA_CENTER,
            spaceBefore=10,
        )
    )
    return styles


STYLES = make_styles()


def p(text: str, style: str = "Body"):
    return Paragraph(text, STYLES[style])


def bullet(items: list[str]):
    return ListFlowable(
        [ListItem(p(item, "Bullet"), bulletColor=colors.black) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=22,
        bulletFontName=FONT,
        bulletFontSize=8,
    )


class FigureBox(Flowable):
    def __init__(self, label: str, width: float = 3.9 * inch, height: float = 3.9 * inch):
        super().__init__()
        self.width = width
        self.height = height
        self.label = label

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(colors.black)
        self.canv.setLineWidth(0.8)
        self.canv.rect(0, 0, self.width, self.height)
        self.canv.setFont(FONT, 9.5)
        self.canv.drawString(8, self.height / 2, self.label)


def add_header_footer(canvas, doc):
    page = canvas.getPageNumber()
    canvas.saveState()
    canvas.setFont(FONT, 10)
    canvas.drawCentredString(letter[0] / 2, 0.45 * inch, str(page))
    canvas.restoreState()


def build_story():
    story = []
    story.append(p("0.1&nbsp;&nbsp;&nbsp;Pipeline", "SectionTitle"))
    story.append(p("0.1.1&nbsp;&nbsp;&nbsp;Kiến trúc tổng quát", "SubTitle"))
    story.append(
        p(
            "Nhằm đảm bảo cho sự linh hoạt và tính đáp ứng cao của sản phẩm, dữ liệu "
            "được thu thập thông qua nhiều nguồn khác nhau và được xử lý theo kiến trúc "
            "tổng quát qua hình thức <b>Medallion Architecture</b>. Theo đó, dữ liệu được "
            "phân lớp tuần tự qua các lớp <i>Bronze - Silver - Gold</i>, tương ứng với "
            "các bước chính theo quy trình <i>ETL - Extract, Transform - Load</i>."
        )
    )
    story.append(
        p(
            "Bên cạnh đó, một lớp phụ là <b>Warehouse</b> được triển khai sau lớp Gold, "
            "sử dụng hệ quản trị cơ sở dữ liệu PostgreSQL như cầu nối để dashboard, API "
            "và các tác tử phân tích có thể kết nối và truy vấn trực tiếp dữ liệu trong "
            "kho dữ liệu."
        )
    )
    story.append(
        p(
            "Dữ liệu trung gian được lưu trữ trên nền tảng MinIO dưới định dạng parquet. "
            "So với phiên bản pipeline ban đầu, cách tổ chức dữ liệu giá đã được điều "
            "chỉnh theo hướng tách biệt giữa <i>partition logic</i> của Dagster và "
            "<i>physical layout</i> trên MinIO. Cụ thể, Dagster vẫn sử dụng partition theo "
            "ngày để theo dõi thời điểm cập nhật, trong khi dữ liệu giá đầy đủ của từng "
            "mã được lưu dưới dạng <b>SYMBOL.parquet</b> tại từng lớp dữ liệu."
        )
    )
    story.append(
        p(
            "Sự điều chỉnh này xuất phát từ đặc thù của dữ liệu giá chứng khoán. Khi doanh "
            "nghiệp thực hiện chia cổ tức, phát hành thêm hoặc thưởng cổ phiếu, toàn bộ chuỗi "
            "giá lịch sử có thể bị điều chỉnh lại. Nếu lưu dữ liệu giá theo partition ngày "
            "và ghi đè toàn bộ các partition lịch sử, chi phí ghi dữ liệu lên MinIO sẽ tăng "
            "đáng kể. Vì vậy, pipeline hiện tại lựa chọn phương án gọi lại chuỗi lịch sử ở "
            "lớp Bronze, nhưng lưu trữ vật lý theo từng mã cổ phiếu để giảm số lượng file cần "
            "ghi và đơn giản hóa luồng kiểm soát chất lượng dữ liệu."
        )
    )

    story.append(p("0.1.2&nbsp;&nbsp;&nbsp;Data Lineage", "SubTitle"))
    story.append(p("Lớp Bronze", "LayerTitle"))
    story.append(
        p(
            "Lớp <i>Bronze</i> có nhiệm vụ chính là thu thập dữ liệu thô từ các nguồn đầu vào. "
            "Cụ thể, lớp này thực hiện cào dữ liệu tin tức từ Vietstock và Vietcap, đồng thời "
            "khai thác dữ liệu doanh nghiệp, dữ liệu báo cáo tài chính, dữ liệu sự kiện và dữ "
            "liệu giá thông qua thư viện Vnstock."
        )
    )
    story.append(
        bullet(
            [
                "<b>bronze_vietcap_news</b>, <b>bronze_vietstock_news</b>: cào dữ liệu HTML của các bài báo từ Vietcap và Vietstock. Assets được materialize hằng ngày; mỗi lần chạy thu thập dữ liệu của ngày hiện tại và ngày liền trước nhằm hạn chế tình trạng bỏ sót bài viết.",
                "<b>bronze_overview</b>: gọi API từ Vnstock để trích xuất thông tin tổng quan doanh nghiệp như mã cổ phiếu, tên doanh nghiệp, sàn giao dịch, ngành nghề, số lượng cổ phiếu lưu hành và các thông tin định danh khác. Asset này được tổ chức trong thư mục <i>company_info</i> trên MinIO.",
                "<b>bronze_events</b>: gọi API từ Vnstock để trích xuất các sự kiện doanh nghiệp. Khác với luồng ban đầu chỉ nhấn mạnh sự kiện cổ tức, luồng hiện tại giữ lại các nhóm sự kiện có khả năng ảnh hưởng đến quyền lợi cổ đông và chuỗi giá, bao gồm chi trả cổ tức, cổ tức bằng cổ phiếu, phát hành thêm và thưởng cổ phiếu.",
                "<b>bronze_officers</b>, <b>bronze_shareholders</b>: thu thập thông tin ban lãnh đạo, cổ đông lớn và tỷ lệ sở hữu nhằm bổ sung góc nhìn quản trị doanh nghiệp.",
                "<b>bronze_prices_1d</b>: gọi API từ Vnstock để lấy toàn bộ chuỗi giá lịch sử theo ngày cho từng mã cổ phiếu. Kết quả chính được lưu theo cấu trúc <i>bronze/prices/prices_1d/SYMBOL.parquet</i>, trong khi file partition theo ngày chỉ đóng vai trò manifest ghi nhận ngày cập nhật, khoảng ngày có dữ liệu, số dòng và mã băm lịch sử.",
                "<b>bronze_income_statement</b>, <b>bronze_balance_sheet</b>, <b>bronze_cash_flow</b>: gọi API từ Vnstock để trích xuất lần lượt báo cáo kết quả kinh doanh, bảng cân đối kế toán và báo cáo lưu chuyển tiền tệ. Các assets được materialize theo quý và lưu trong thư mục <i>reports</i> trên MinIO.",
            ]
        )
    )

    story.append(p("Lớp Silver", "LayerTitle"))
    story.append(
        p(
            "Lớp <i>Silver</i> thực hiện làm sạch và chuẩn hóa dữ liệu từ lớp Bronze nhằm "
            "phục vụ truy vấn và phân tích. Một thay đổi quan trọng của phiên bản pipeline "
            "hiện tại là lớp Silver không gọi lại API đối với dữ liệu đã có ở Bronze. Điều này "
            "giúp giảm rủi ro dữ liệu bị lệch do thay đổi ở nguồn ngoài, đồng thời bảo đảm "
            "nguyên tắc mỗi lớp dữ liệu chỉ phụ thuộc vào lớp trước nó."
        )
    )
    story.append(
        bullet(
            [
                "<b>silver_news</b>: chuẩn hóa và hợp nhất dữ liệu tin tức từ Vietcap và Vietstock, bao gồm tiêu đề, ngày đăng, mã cổ phiếu liên quan, tóm tắt và nhãn cảm xúc.",
                "<b>silver_reports</b>: chuẩn hóa báo cáo tài chính, đưa đơn vị về tỷ đồng và hợp nhất báo cáo kết quả kinh doanh, bảng cân đối kế toán, lưu chuyển tiền tệ thành một bảng fact thống nhất.",
                "<b>silver_prices_1d</b>: đọc dữ liệu giá từ các file SYMBOL.parquet của Bronze, chuẩn hóa schema và ghi ra <i>silver/prices_1d/SYMBOL.parquet</i>. Asset này sử dụng manifest theo ngày để ghi nhận các mã được append, overwrite hoặc bỏ qua. Khi phát hiện sự kiện có ngày giao dịch không hưởng quyền nằm trong khoảng dữ liệu mới, Silver sẽ overwrite lại toàn bộ file của mã tương ứng; ngược lại, nếu lịch sử không thay đổi, asset chỉ append các ngày mới.",
                "<b>silver_overview</b>: chuẩn hóa thông tin tổng quan doanh nghiệp dựa trực tiếp trên dữ liệu Bronze, không gọi thêm danh sách mã từ Vnstock. Các trường như symbol, organ_short_name, listing, sector và icb_code được ánh xạ về ticker, name, trading_floor, industry và subindustry để tránh hiện tượng mất mã hoặc lệch dữ liệu khi nguồn API thay đổi.",
                "<b>silver_events</b>, <b>silver_shareholders</b>, <b>silver_officers</b>: chuẩn hóa lần lượt thông tin sự kiện, cổ đông và ban lãnh đạo. Riêng events giữ lại các trường như event_id, event_type_id, record_date, exright_date, rate_original và rate_split để phục vụ điều chỉnh giá, điều chỉnh số lượng cổ phiếu và phân tích sự kiện doanh nghiệp ở lớp Gold.",
            ]
        )
    )

    story.append(p("Lớp Gold", "LayerTitle"))
    story.append(
        p(
            "Lớp <i>Gold</i> đóng vai trò cung cấp các bảng dữ liệu cuối cùng phục vụ truy vấn "
            "trực tiếp, dashboard và các tác tử phân tích. Tại lớp này, dữ liệu tiếp tục được "
            "làm giàu bằng các chỉ số tài chính, chỉ số định giá và các trường phục vụ phân tích "
            "xu hướng."
        )
    )
    story.append(
        bullet(
            [
                "<b>gold_overview</b>: chuẩn hóa lần cuối dữ liệu tổng quan, loại trùng theo ticker và giữ bản mới nhất theo date_fetched. Khi đẩy sang Warehouse, bảng overview được upsert theo ticker để tránh phát sinh bản ghi trùng sau mỗi lần materialize.",
                "<b>gold_events</b>: lọc các sự kiện có event_type_id thuộc nhóm 1, 2, 3, 4 và bắt buộc có cả record_date lẫn exright_date hợp lệ. Bảng này giữ schema sự kiện tương đối đầy đủ và sử dụng event_id làm khóa khi ghi sang Warehouse.",
                "<b>gold_reports</b>: chuẩn hóa báo cáo tài chính thành cấu trúc phù hợp cho dashboard chi tiết. Các chỉ tiêu được chuẩn hóa về item_id, criteria, line_item_key và phân loại theo report_type, giúp giao diện có thể hiển thị báo cáo theo cấu trúc có thứ bậc.",
                "<b>gold_ticker_metric</b>: tính toán và hợp nhất các chỉ số tài chính quan trọng như EPS, BVPS, ROE, ROA, ROIC, biên lợi nhuận, NIM và các chỉ số đòn bẩy. EPS và BVPS được tính từ lợi nhuận TTM, vốn chủ sở hữu và số lượng cổ phiếu lưu hành trong silver_ticker_metric; trong trường hợp có sự kiện thay đổi số lượng cổ phiếu, mẫu số được điều chỉnh ngược về kỳ báo cáo. Nếu không đủ dữ liệu để điều chỉnh, pipeline sử dụng number_of_shares_mkt_cap gốc làm fallback.",
                "<b>gold_prices_1d</b>: đọc dữ liệu từ Silver theo manifest hoặc trực tiếp từ symbol files, bổ sung các chỉ số định giá như P/E, P/B, market_cap và các cột thay đổi giá theo nhiều khung thời gian. Dữ liệu chính tiếp tục được ghi theo <i>gold/prices_1d/SYMBOL.parquet</i>, còn partition ngày đóng vai trò manifest phục vụ Dagster và Warehouse.",
                "<b>warehouse_prices_1d</b>: không ghi manifest vào PostgreSQL. Asset này đọc manifest của Gold, nạp lại các file symbol tương ứng, lọc theo khoảng output_start_date và output_end_date rồi upsert dữ liệu thật theo khóa ticker và date.",
            ]
        )
    )

    story.append(p("0.1.3&nbsp;&nbsp;&nbsp;Data Source", "SubTitle"))
    story.append(
        p(
            "Vietstock là một trong những cổng thông tin tài chính và chứng khoán hàng đầu tại "
            "Việt Nam, cung cấp dữ liệu về thị trường chứng khoán, thông tin doanh nghiệp, báo cáo "
            "tài chính, sự kiện doanh nghiệp và tin tức kinh tế được cập nhật liên tục. Trong đề tài "
            "này, Vietstock được sử dụng để thu thập tin tức thị trường và các dữ liệu phục vụ quá "
            "trình phân tích cổ phiếu."
        )
    )
    story.append(
        p(
            "Vietcap là nền tảng cung cấp thông tin và dịch vụ tài chính của Công ty Cổ phần Chứng "
            "khoán Vietcap. Trong hệ thống, Vietcap được sử dụng như một nguồn dữ liệu bổ sung cho "
            "tin tức doanh nghiệp, giúp mở rộng phạm vi thông tin và tăng độ tin cậy của dữ liệu "
            "được thu thập từ nhiều nguồn khác nhau."
        )
    )
    story.append(
        p(
            "Vnstock API là thư viện Python hỗ trợ truy cập dữ liệu chứng khoán Việt Nam thông qua "
            "giao diện lập trình thống nhất. Thư viện cho phép thu thập nhiều loại dữ liệu như giá "
            "cổ phiếu, thông tin doanh nghiệp, báo cáo tài chính, sự kiện doanh nghiệp, cơ cấu cổ "
            "đông và ban lãnh đạo. Trong pipeline hiện tại, Vnstock đóng vai trò là nguồn dữ liệu "
            "chính của lớp Bronze."
        )
    )
    story.append(
        p(
            "Cotuc.vn được sử dụng như một nguồn tham khảo miễn phí đối với các thông tin liên quan "
            "đến cổ đông và sự kiện cổ tức. Tuy nhiên, do dữ liệu sự kiện doanh nghiệp có thể không "
            "đồng nhất giữa các nguồn, pipeline hiện tại ưu tiên chuẩn hóa event_id, record_date và "
            "exright_date nhằm bảo đảm khả năng đối chiếu và xử lý lặp lại."
        )
    )

    story.append(p("0.1.4&nbsp;&nbsp;&nbsp;Cơ sở dữ liệu", "SubTitle"))
    story.append(
        p(
            "Các bảng trong lớp Warehouse được tổ chức nhằm phục vụ truy vấn, phân tích và trực quan "
            "hóa dữ liệu một cách hiệu quả. So với thiết kế ban đầu, Warehouse hiện nay không phản ánh "
            "trực tiếp cách lưu trữ vật lý trên MinIO. Thay vào đó, MinIO chịu trách nhiệm lưu trữ dữ "
            "liệu dạng file theo từng lớp, còn Warehouse chỉ lưu các bảng đã được chuẩn hóa hoặc làm "
            "giàu từ lớp Gold."
        )
    )
    story.append(p("Bảng overview.", "LayerTitle"))
    story.append(
        p(
            "Bảng overview lưu trữ thông tin tổng quan của doanh nghiệp theo từng mã cổ phiếu. Bảng "
            "này được upsert theo ticker, giúp tránh tình trạng trùng dữ liệu sau nhiều lần chạy pipeline. "
            "Dữ liệu bao gồm tên doanh nghiệp, sàn giao dịch, ngành nghề, nhóm ngành, hồ sơ doanh nghiệp, "
            "số lượng cổ phiếu phát hành và các trường định danh khác."
        )
    )
    story.append(p("Bảng prices.", "LayerTitle"))
    story.append(
        p(
            "Bảng prices chứa dữ liệu giao dịch hằng ngày của từng mã cổ phiếu, bao gồm ngày giao dịch, "
            "giá mở cửa, giá cao nhất, giá thấp nhất, giá đóng cửa, khối lượng, vốn hóa và các chỉ số "
            "định giá theo thời giá. Dữ liệu được upsert từ manifest của Gold thay vì ghi trực tiếp từ "
            "partition ngày, bảo đảm rằng Warehouse nhận dữ liệu thật sau khi pipeline đã xử lý theo "
            "symbol files."
        )
    )
    story.append(p("Bảng reports.", "LayerTitle"))
    story.append(
        p(
            "Bảng reports lưu trữ dữ liệu báo cáo tài chính đã được chuẩn hóa dưới dạng fact table. "
            "Cấu trúc gồm mã cổ phiếu, năm, quý, loại báo cáo, chỉ tiêu, item_id và giá trị. Cách tổ "
            "chức này giúp dữ liệu tài chính dễ mở rộng, thuận tiện cho việc truy vấn dashboard chi "
            "tiết và tính toán các chỉ số tài chính tại lớp Gold."
        )
    )
    story.append(p("Bảng ticker_metric.", "LayerTitle"))
    story.append(
        p(
            "Bảng ticker_metric lưu trữ các chỉ số tài chính đã được tính toán và chuẩn hóa theo từng "
            "kỳ báo cáo. Ngoài EPS, BVPS, ROE và ROA, bảng còn bao gồm ROIC, các chỉ số biên lợi nhuận, "
            "đòn bẩy tài chính, dividend_yield, NIM và cost_to_income đối với nhóm ngân hàng. Giao diện "
            "BCTC chi tiết sử dụng trực tiếp bảng này để hiển thị chuỗi chỉ số theo quý hoặc theo năm. "
            "Đối với chế độ năm, hệ thống sử dụng chỉ số cuối năm hoặc kỳ mới nhất trong năm thay vì "
            "cộng hoặc lấy trung bình cơ học các tỷ số."
        )
    )
    story.append(p("Bảng shareholders và officers.", "LayerTitle"))
    story.append(
        p(
            "Các bảng shareholders và officers lưu trữ thông tin về cơ cấu cổ đông và ban lãnh đạo "
            "doanh nghiệp. Dữ liệu hỗ trợ phân tích mức độ tập trung sở hữu, vai trò của cổ đông lớn "
            "và mức độ gắn kết lợi ích giữa ban lãnh đạo với cổ đông."
        )
    )
    story.append(p("Bảng events.", "LayerTitle"))
    story.append(
        p(
            "Bảng events lưu trữ các sự kiện doanh nghiệp liên quan đến từng mã cổ phiếu như chi trả "
            "cổ tức, cổ tức bằng cổ phiếu, phát hành thêm, quyền mua và thưởng cổ phiếu. Pipeline hiện "
            "tại yêu cầu các sự kiện quan trọng phải có record_date và exright_date để bảo đảm khả năng "
            "đối chiếu, giải thích biến động giá và phục vụ các bước điều chỉnh chuỗi giá hoặc số lượng "
            "cổ phiếu lưu hành."
        )
    )
    story.append(p("Bảng news.", "LayerTitle"))
    story.append(
        p(
            "Bảng news lưu trữ dữ liệu tin tức được thu thập từ Vietcap và Vietstock. Các trường dữ "
            "liệu bao gồm đường dẫn bài viết, tiêu đề, ngày đăng, mã cổ phiếu liên quan, nguồn tin, "
            "tóm tắt nội dung, chuyên mục, từ khóa và nhãn cảm xúc nếu có. Dữ liệu này giúp bổ sung "
            "góc nhìn tin tức cho hệ thống phân tích."
        )
    )

    story.append(p("0.1.5&nbsp;&nbsp;&nbsp;Các vấn đề tồn đọng và hướng xử lý", "SubTitle"))
    story.append(
        bullet(
            [
                "<b>Điều chỉnh hồi tố chuỗi giá:</b> dữ liệu giá có thể thay đổi toàn bộ lịch sử sau các sự kiện cổ tức, phát hành thêm hoặc thưởng cổ phiếu. Hướng xử lý hiện tại là refresh full history tại Bronze nhưng lưu theo SYMBOL.parquet, kết hợp manifest và history_hash để quyết định append hay overwrite ở Silver và Gold.",
                "<b>Phân biệt partition và file vật lý:</b> trong pipeline mới, partition ngày dùng để Dagster theo dõi lần cập nhật, không còn đại diện cho dữ liệu giá của riêng ngày đó. Hướng xử lý là chuẩn hóa quy ước manifest theo ngày và symbol file theo mã, đồng thời bổ sung cơ chế fallback đọc trực tiếp symbol files khi thiếu manifest.",
                "<b>Rủi ro gọi API ngoài lớp Bronze:</b> việc gọi lại API tại Silver hoặc Gold có thể làm dữ liệu bị lệch so với lớp Bronze. Hướng xử lý là loại bỏ các lệnh lấy universe hoặc thông tin doanh nghiệp từ API trong Silver/Gold, đặc biệt ở silver_prices_1d và silver_overview.",
                "<b>Chất lượng dữ liệu sự kiện:</b> một số sự kiện có exright_date nhưng thiếu record_date, hoặc khác biệt giữa các nguồn. Hướng xử lý là lọc chặt tại gold_events đối với các sự kiện đưa vào Warehouse, đồng thời giữ log overwrite ở silver_prices_1d với mã cổ phiếu, exright_date và event_title để dễ kiểm tra.",
                "<b>Hiệu năng ghi dữ liệu:</b> nếu ghi lại nhiều partition lịch sử, chi phí I/O trên MinIO tăng cao. Hướng xử lý là ghi đè theo từng symbol thay vì theo từng ngày, đồng thời chỉ upsert dữ liệu thật vào Warehouse dựa trên output_start_date và output_end_date trong manifest.",
                "<b>Độ nhất quán của chỉ số tài chính:</b> các chỉ số theo cổ phiếu phụ thuộc vào số lượng cổ phiếu lưu hành, vốn có thể thay đổi do sự kiện doanh nghiệp. Hướng xử lý hiện tại là tính EPS/BVPS từ báo cáo tài chính, kết hợp number_of_shares_mkt_cap đã điều chỉnh ngược theo sự kiện cổ phiếu; khi không đủ dữ liệu, hệ thống sử dụng số cổ phiếu gốc làm fallback có kiểm soát.",
            ]
        )
    )
    story.append(
        p(
            "Nhìn chung, phiên bản pipeline hiện tại đã chuyển trọng tâm từ mô hình lưu dữ liệu giá "
            "theo partition ngày sang mô hình quản trị chuỗi thời gian theo từng mã cổ phiếu. Sự thay "
            "đổi này giúp pipeline phù hợp hơn với đặc thù dữ liệu chứng khoán, đặc biệt trong bối cảnh "
            "các sự kiện doanh nghiệp có thể làm thay đổi lại toàn bộ chuỗi giá lịch sử."
        )
    )

    for label, caption in [
        ("data_lineage.png", "Hình 1: Global Lineage của luồng dữ liệu"),
        ("Bronze.png", "Hình 2: Các thư mục được lưu ở lớp Bronze trong MinIO"),
        ("toSilver.png", "Hình 3: Luồng dữ liệu từ Bronze sang Silver trong MinIO"),
        ("toGold.png", "Hình 4: Luồng dữ liệu từ Silver sang Gold trong MinIO"),
        ("schemas.png", "Hình 5: Schema cho các bảng dữ liệu trong Warehouse"),
    ]:
        story.append(PageBreak())
        story.append(Spacer(1, 2.0 * inch))
        story.append(FigureBox(label))
        story.append(p(caption, "Caption"))

    return story


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=letter,
        leftMargin=1.45 * inch,
        rightMargin=1.25 * inch,
        topMargin=1.55 * inch,
        bottomMargin=0.75 * inch,
    )
    doc.build(build_story(), onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
