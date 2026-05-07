"""
AMAN ERP — Industry Chart of Accounts Templates
قوالب شجرة الحسابات حسب نوع النشاط

كل نشاط يحصل على:
1. الحسابات الأساسية المشتركة (CORE_ACCOUNTS)
2. حسابات متخصصة خاصة بنشاطه (INDUSTRY_ACCOUNTS[key])

الترقيم: SOCPA / IFRS
  1xxxx = الأصول
  2xxxx = الالتزامات
  3xxxx = حقوق الملكية
  4xxxx = الإيرادات
  5xxxx = تكلفة المبيعات
  6xxxx = المصاريف التشغيلية
  7xxxx = مصاريف أخرى / مالية
"""

from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Key-to-Code normalization (frontend sends RT/FB/MF, backend uses retail/restaurant/manufacturing)
# ═══════════════════════════════════════════════════════════════════════════════
_KEY_TO_CODE = {
    'RT': 'retail', 'WS': 'wholesale', 'FB': 'restaurant', 'MF': 'manufacturing',
    'CN': 'construction', 'SV': 'services', 'PH': 'pharmacy', 'WK': 'workshop',
    'EC': 'ecommerce', 'LG': 'logistics', 'AG': 'agriculture', 'GN': 'general',
}

def normalize_industry_key(value: str) -> str:
    """Convert short key (RT/FB) or code name (retail/restaurant) to code name."""
    if not value:
        return 'general'
    upper = value.upper()
    if upper in _KEY_TO_CODE:
        return _KEY_TO_CODE[upper]
    # Already a code name or unknown → return as-is
    return value.lower()

# ═══════════════════════════════════════════════════════════════════════════════
# الحسابات الأساسية المشتركة لكل الأنشطة
# (account_code, name_ar, name_en, account_type, parent_code, is_header)
# ═══════════════════════════════════════════════════════════════════════════════
CORE_ACCOUNTS = [
    # ──── الأصول ────
    ("1",      "الأصول",                        "Assets",                       "asset",      None,    True),
    ("11",     "أصول متداولة",                   "Current Assets",               "asset",      "1",     True),
    ("11001",  "النقد وما في حكمه",              "Cash & Equivalents",           "asset",      "11",    True),
    ("11010",  "الصندوق الرئيسي",               "Main Cash Box",                "asset",      "11001", False),
    ("11020",  "البنك",                          "Bank Account",                 "asset",      "11001", False),
    ("12",     "ذمم مدينة",                      "Receivables",                  "asset",      "1",     True),
    ("12001",  "العملاء",                        "Accounts Receivable",          "asset",      "12",    False),
    ("12010",  "شيكات تحت التحصيل",             "Checks Receivable",            "asset",      "12",    False),
    ("12020",  "أوراق قبض",                     "Notes Receivable",             "asset",      "12",    False),
    ("15",     "مصاريف مدفوعة مقدماً",           "Prepaid Expenses",             "asset",      "1",     True),
    ("15001",  "مصروفات مدفوعة مقدماً",          "Prepaid Expenses",             "asset",      "15",    False),
    ("15010",  "ضريبة مدخلات VAT",              "Input VAT",                    "asset",      "15",    False),
    ("16",     "أصول ثابتة",                     "Fixed Assets",                 "asset",      "1",     True),
    ("16001",  "أثاث ومعدات مكتبية",             "Furniture & Office Equipment", "asset",      "16",    False),
    ("16010",  "أجهزة حاسوب",                   "Computers",                    "asset",      "16",    False),
    ("16020",  "سيارات",                         "Vehicles",                     "asset",      "16",    False),
    ("18",     "إهلاك متراكم",                   "Accumulated Depreciation",     "asset",      "1",     True),
    ("18001",  "إهلاك متراكم — أثاث",            "Accum. Depr. — Furniture",     "asset",      "18",    False),
    ("18002",  "إهلاك متراكم — حاسوب",           "Accum. Depr. — Computers",     "asset",      "18",    False),
    ("18003",  "إهلاك متراكم — سيارات",          "Accum. Depr. — Vehicles",      "asset",      "18",    False),

    # ──── الالتزامات ────
    ("2",      "الالتزامات",                     "Liabilities",                  "liability",  None,    True),
    ("21",     "التزامات متداولة",               "Current Liabilities",          "liability",  "2",     True),
    ("21001",  "الموردين",                       "Accounts Payable",             "liability",  "21",    False),
    ("21010",  "مصاريف مستحقة",                  "Accrued Expenses",             "liability",  "21",    False),
    ("21020",  "شيكات تحت الدفع",               "Checks Payable",               "liability",  "21",    False),
    ("21030",  "أوراق دفع",                     "Notes Payable",                "liability",  "21",    False),
    ("21040",  "ضريبة مخرجات VAT",              "Output VAT",                   "liability",  "21",    False),
    ("21050",  "ضريبة القيمة المضافة المستحقة",   "VAT Payable",                  "liability",  "21",    False),
    ("21055",  "استقطاع ضريبي مستحق WHT",        "WHT Payable",                  "liability",  "21",    False),
    ("21060",  "التأمينات الاجتماعية GOSI",       "GOSI Payable",                 "liability",  "21",    False),
    ("21070",  "رواتب مستحقة",                   "Salaries Payable",             "liability",  "21",    False),
    ("21080",  "إيرادات مقدمة / عربون عملاء",     "Deferred Revenue / Deposits",  "liability",  "21",    False),
    ("22",     "التزامات طويلة الأجل",            "Long-term Liabilities",        "liability",  "2",     True),
    ("22001",  "مخصص نهاية الخدمة",              "End of Service Provision",     "liability",  "22",    False),

    # ──── حقوق الملكية ────
    ("3",      "حقوق الملكية",                   "Equity",                       "equity",     None,    True),
    ("31001",  "رأس المال",                      "Capital",                      "equity",     "3",     False),
    ("32001",  "أرباح (خسائر) مُبقاة",            "Retained Earnings",            "equity",     "3",     False),
    ("33001",  "أرباح (خسائر) العام الحالي",       "Current Year P&L",             "equity",     "3",     False),

    # ──── الإيرادات ────
    ("4",      "الإيرادات",                      "Revenue",                      "revenue",    None,    True),
    ("41",     "إيرادات النشاط الرئيسي",          "Operating Revenue",            "revenue",    "4",     True),
    ("41001",  "إيرادات المبيعات",               "Sales Revenue",                "revenue",    "41",    False),
    ("42",     "إيرادات أخرى",                   "Other Revenue",                "revenue",    "4",     True),
    ("42001",  "إيرادات متنوعة",                 "Miscellaneous Revenue",        "revenue",    "42",    False),
    ("42010",  "خصم مكتسب",                     "Discount Earned",              "revenue",    "42",    False),
    ("42020",  "أرباح فروق عملة",                "Foreign Exchange Gains",       "revenue",    "42",    False),
    ("42021",  "أرباح فروق عملة (غير محققة)",     "Unrealized FX Gains",          "revenue",    "42",    False),

    # ──── تكلفة المبيعات ────
    ("5",      "تكلفة المبيعات",                 "Cost of Sales",                "expense",    None,    True),
    ("51001",  "تكلفة البضاعة المباعة",           "Cost of Goods Sold",           "expense",    "5",     False),

    # ──── المصاريف التشغيلية ────
    ("6",      "المصاريف التشغيلية",              "Operating Expenses",           "expense",    None,    True),
    ("61",     "رواتب وأجور",                    "Salaries & Wages",             "expense",    "6",     True),
    ("61001",  "رواتب وأجور",                    "Salaries & Wages",             "expense",    "61",    False),
    ("61010",  "بدلات وعلاوات",                  "Allowances",                   "expense",    "61",    False),
    ("61020",  "تأمينات اجتماعية GOSI",           "GOSI Expense",                 "expense",    "61",    False),
    ("62",     "إيجارات",                        "Rent",                         "expense",    "6",     True),
    ("62001",  "إيجار",                          "Rent Expense",                 "expense",    "62",    False),
    ("63",     "مرافق",                          "Utilities",                    "expense",    "6",     True),
    ("63001",  "كهرباء ومياه",                   "Electricity & Water",          "expense",    "63",    False),
    ("63010",  "اتصالات وإنترنت",                "Telecommunications",           "expense",    "63",    False),
    ("64",     "تسويق وإعلان",                   "Marketing & Advertising",      "expense",    "6",     True),
    ("64001",  "تسويق وإعلان",                   "Marketing & Advertising",      "expense",    "64",    False),
    ("65",     "مصاريف إدارية عامة",              "General & Admin",              "expense",    "6",     True),
    ("65001",  "مصاريف إدارية عامة",              "General & Admin Expenses",     "expense",    "65",    False),
    ("65010",  "صيانة وإصلاح",                   "Maintenance & Repair",         "expense",    "65",    False),
    ("65020",  "تأمين",                          "Insurance",                    "expense",    "65",    False),
    ("65030",  "رسوم حكومية",                    "Government Fees",              "expense",    "65",    False),
    ("66",     "إهلاك وإطفاء",                   "Depreciation & Amortization",  "expense",    "6",     True),
    ("66001",  "إهلاك",                          "Depreciation Expense",         "expense",    "66",    False),
    ("66010",  "سفر وانتقالات",                  "Travel & Transport",           "expense",    "66",    False),

    # ──── مصاريف مالية ────
    ("7",      "مصاريف مالية وأخرى",             "Financial & Other Expenses",   "expense",    None,    True),
    ("71001",  "رسوم بنكية",                     "Bank Charges",                 "expense",    "7",     False),
    ("71010",  "خسائر فروق عملة",                "Foreign Exchange Losses",      "expense",    "7",     False),
    ("71011",  "خسائر فروق عملة (غير محققة)",     "Unrealized FX Losses",         "expense",    "7",     False),
    ("71020",  "خصم ممنوح",                     "Discount Granted",             "expense",    "7",     False),
]


# ═══════════════════════════════════════════════════════════════════════════════
# الحسابات المتخصصة لكل نشاط
# ═══════════════════════════════════════════════════════════════════════════════

INDUSTRY_ACCOUNTS = {
    # ──── 🛍️ RT — التجزئة ────
    "retail": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون بضاعة",                  "Merchandise Inventory",        "asset",    "13",    False),
        ("13010",  "بضاعة بالطريق",                "Goods in Transit",             "asset",    "13",    False),
        ("41010",  "مبيعات نقدية POS",              "POS Cash Sales",               "revenue",  "41",    False),
        ("41020",  "مردودات مبيعات",               "Sales Returns",                "revenue",  "41",    False),
        ("41030",  "خصم مبيعات تجاري",             "Trade Discount",               "revenue",  "41",    False),
        ("51010",  "تكلفة بضاعة مُباعة — تجزئة",    "COGS — Retail",                "expense",  "5",     False),
        ("51020",  "فروقات جرد",                   "Inventory Variance",           "expense",  "5",     False),
        ("51030",  "تلف وهالك بضاعة",              "Spoilage & Waste",             "expense",  "5",     False),
        ("64010",  "برامج ولاء ونقاط",              "Loyalty Programs",             "expense",  "64",    False),
        ("65040",  "مصاريف تعبئة وتغليف",           "Packaging Expenses",           "expense",  "65",    False),
    ],

    # ──── 📦 WS — الجملة والتوزيع ────
    "wholesale": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون بضاعة",                  "Merchandise Inventory",        "asset",    "13",    False),
        ("13010",  "بضاعة بالطريق",                "Goods in Transit",             "asset",    "13",    False),
        ("13020",  "بضاعة لدى الوكلاء",             "Consignment Inventory",        "asset",    "13",    False),
        ("12030",  "ذمم وكلاء",                    "Agent Receivables",            "asset",    "12",    False),
        ("41010",  "مبيعات جملة",                  "Wholesale Sales",              "revenue",  "41",    False),
        ("41020",  "مردودات مبيعات",               "Sales Returns",                "revenue",  "41",    False),
        ("41030",  "خصم كمية",                    "Quantity Discount",            "revenue",  "41",    False),
        ("51010",  "تكلفة بضاعة مُباعة — جملة",     "COGS — Wholesale",             "expense",  "5",     False),
        ("51020",  "عمولات وكلاء",                 "Agent Commissions",            "expense",  "5",     False),
        ("65040",  "مصاريف شحن صادر",              "Outbound Shipping",            "expense",  "65",    False),
        ("65050",  "مصاريف تخزين",                 "Storage Expenses",             "expense",  "65",    False),
        ("65060",  "تكاليف جمركية",                "Customs Duties",               "expense",  "65",    False),
    ],

    # ──── 🍽️ FB — المطاعم والمقاهي ────
    "restaurant": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون مواد غذائية",             "Food Inventory",               "asset",    "13",    False),
        ("13010",  "مخزون مشروبات",                "Beverage Inventory",           "asset",    "13",    False),
        ("13020",  "مخزون مواد تغليف",              "Packaging Materials",          "asset",    "13",    False),
        ("16030",  "معدات مطبخ",                   "Kitchen Equipment",            "asset",    "16",    False),
        ("18004",  "إهلاك متراكم — معدات مطبخ",     "Accum. Depr. — Kitchen",       "asset",    "18",    False),
        ("41010",  "إيرادات مطعم Dine-in",          "Dine-in Revenue",              "revenue",  "41",    False),
        ("41020",  "إيرادات توصيل",                "Delivery Revenue",             "revenue",  "41",    False),
        ("41030",  "إيرادات تموين / كيترنق",        "Catering Revenue",             "revenue",  "41",    False),
        ("51010",  "تكلفة الطعام Food Cost",        "Food Cost",                    "expense",  "5",     False),
        ("51020",  "تكلفة المشروبات",               "Beverage Cost",                "expense",  "5",     False),
        ("51030",  "تكلفة التغليف",                "Packaging Cost",               "expense",  "5",     False),
        ("51040",  "هالك وتلف غذائي",              "Food Waste & Spoilage",        "expense",  "5",     False),
        ("61030",  "أجور طهاة Kitchen Labor",       "Kitchen Labor",                "expense",  "61",    False),
        ("61040",  "أجور خدمة / ويتر",             "Service Staff Wages",          "expense",  "61",    False),
        ("62010",  "إيجار مطعم",                   "Restaurant Rent",              "expense",  "62",    False),
        ("63020",  "غاز طبخ",                     "Cooking Gas",                  "expense",  "63",    False),
        ("64010",  "عمولات تطبيقات التوصيل",        "Delivery App Commissions",     "expense",  "64",    False),
        ("65040",  "أدوات نظافة مطعم",              "Restaurant Cleaning Supplies", "expense",  "65",    False),
    ],

    # ──── 🏭 MF — التصنيع والإنتاج ────
    "manufacturing": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون مواد خام",               "Raw Materials Inventory",      "asset",    "13",    False),
        ("13010",  "مخزون تحت التشغيل WIP",        "Work in Progress",             "asset",    "13",    False),
        ("13020",  "مخزون إنتاج تام",              "Finished Goods",               "asset",    "13",    False),
        ("13030",  "مخزون قطع غيار",               "Spare Parts Inventory",        "asset",    "13",    False),
        ("13040",  "مخزون مواد تعبئة",              "Packaging Materials",          "asset",    "13",    False),
        ("16030",  "آلات ومعدات صناعية",            "Industrial Machinery",         "asset",    "16",    False),
        ("16040",  "خطوط إنتاج",                  "Production Lines",             "asset",    "16",    False),
        ("18004",  "إهلاك متراكم — آلات",           "Accum. Depr. — Machinery",     "asset",    "18",    False),
        ("18005",  "إهلاك متراكم — خطوط إنتاج",     "Accum. Depr. — Prod. Lines",   "asset",    "18",    False),
        ("41010",  "مبيعات منتجات مُصنّعة",          "Manufactured Product Sales",   "revenue",  "41",    False),
        ("41020",  "مبيعات مخلفات تصنيع",           "Scrap Sales",                  "revenue",  "41",    False),
        ("51010",  "تكلفة مواد خام مستخدمة",        "Raw Materials Used",           "expense",  "5",     False),
        ("51020",  "أجور عمالة مباشرة",             "Direct Labor",                 "expense",  "5",     False),
        ("51030",  "تكاليف صناعية غير مباشرة",      "Manufacturing Overhead",       "expense",  "5",     False),
        ("51040",  "تكلفة هدر وتلف إنتاج",          "Production Waste/Scrap",       "expense",  "5",     False),
        ("51050",  "فروقات تكلفة معيارية",          "Standard Cost Variance",       "expense",  "5",     False),
        ("61030",  "أجور عمال الإنتاج",             "Production Workers Wages",     "expense",  "61",    False),
        ("65040",  "صيانة آلات ومعدات",             "Machinery Maintenance",        "expense",  "65",    False),
        ("65050",  "قطع غيار آلات",                "Machine Spare Parts",          "expense",  "65",    False),
        ("66020",  "إهلاك آلات",                   "Machinery Depreciation",       "expense",  "66",    False),
    ],

    # ──── 🏗️ CN — المقاولات والمشاريع ────
    "construction": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون مواد بناء",               "Building Materials Inventory",  "asset",    "13",    False),
        ("13010",  "مخزون مواد بالموقع",            "On-site Materials",            "asset",    "13",    False),
        ("12030",  "محتجزات لدى العملاء",           "Retention Receivable",         "asset",    "12",    False),
        ("15020",  "تكاليف مشاريع مؤجلة",           "Deferred Project Costs",       "asset",    "15",    False),
        ("16030",  "معدات ثقيلة",                  "Heavy Equipment",              "asset",    "16",    False),
        ("16040",  "سقالات وقوالب",                "Scaffolding & Formwork",       "asset",    "16",    False),
        ("18004",  "إهلاك متراكم — معدات ثقيلة",    "Accum. Depr. — Heavy Equip.",  "asset",    "18",    False),
        ("21090",  "محتجزات موردين",               "Retention Payable",            "liability","21",    False),
        ("21100",  "مقاولين من الباطن — مستحقات",   "Subcontractor Payables",       "liability","21",    False),
        ("41010",  "إيرادات عقود إنشاءات",          "Construction Contract Revenue","revenue",  "41",    False),
        ("41020",  "إيرادات مستخلصات",             "Progress Billing Revenue",     "revenue",  "41",    False),
        ("41030",  "إيرادات أوامر تغيير",           "Change Order Revenue",         "revenue",  "41",    False),
        ("51010",  "تكلفة مواد بناء مباشرة",        "Direct Materials Cost",        "expense",  "5",     False),
        ("51020",  "تكلفة عمالة موقع مباشرة",       "Direct Site Labor",            "expense",  "5",     False),
        ("51030",  "تكلفة مقاولين من الباطن",       "Subcontractor Cost",           "expense",  "5",     False),
        ("51040",  "تكاليف معدات مشروع",           "Project Equipment Cost",       "expense",  "5",     False),
        ("51050",  "تكاليف غير مباشرة للمشروع",     "Project Indirect Cost",        "expense",  "5",     False),
        ("65040",  "صيانة معدات ثقيلة",             "Heavy Equipment Maintenance",  "expense",  "65",    False),
        ("66020",  "إهلاك معدات ثقيلة",             "Heavy Equipment Depreciation", "expense",  "66",    False),
    ],

    # ──── 💼 SV — الخدمات المهنية ────
    "services": [
        ("41010",  "إيرادات استشارات",             "Consulting Revenue",           "revenue",  "41",    False),
        ("41020",  "إيرادات صيانة ودعم",            "Support & Maintenance Revenue","revenue",  "41",    False),
        ("41030",  "إيرادات تدريب",                "Training Revenue",             "revenue",  "41",    False),
        ("41040",  "إيرادات اشتراكات Retainer",     "Retainer Revenue",             "revenue",  "41",    False),
        ("42030",  "إيرادات مكافآت نجاح",           "Success Fee Revenue",          "revenue",  "42",    False),
        ("15020",  "أعمال تحت التنفيذ — خدمات",     "WIP — Services",               "asset",    "15",    False),
        ("51010",  "تكلفة ساعات عمل مباشرة",        "Direct Labor Hours Cost",      "expense",  "5",     False),
        ("51020",  "تكلفة خبراء خارجيين",           "External Experts Cost",        "expense",  "5",     False),
        ("61030",  "أجور استشاريين",               "Consultant Wages",             "expense",  "61",    False),
        ("66030",  "إطفاء أصول غير ملموسة",         "Amortization — Intangibles",   "expense",  "66",    False),
    ],

    # ──── 💊 PH — صيدليات ومستلزمات طبية ────
    "pharmacy": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون أدوية",                  "Drug Inventory",               "asset",    "13",    False),
        ("13010",  "مخزون مستلزمات طبية",           "Medical Supplies Inventory",   "asset",    "13",    False),
        ("13020",  "أدوية مُقاربة الصلاحية",         "Near-expiry Drugs",            "asset",    "13",    False),
        ("13030",  "أدوية منتهية للإتلاف",           "Expired Drugs — Disposal",     "asset",    "13",    False),
        ("16030",  "معدات طبية / ثلاجات أدوية",     "Medical Equipment / Fridges",  "asset",    "16",    False),
        ("18004",  "إهلاك متراكم — معدات طبية",     "Accum. Depr. — Medical Equip.","asset",    "18",    False),
        ("41010",  "مبيعات أدوية",                 "Drug Sales",                   "revenue",  "41",    False),
        ("41020",  "مبيعات مستلزمات طبية",          "Medical Supplies Sales",       "revenue",  "41",    False),
        ("41030",  "خدمات فحص / استشارة صيدلانية",  "Pharma Consultation Services", "revenue",  "41",    False),
        ("41040",  "مردودات أدوية",                "Drug Returns",                 "revenue",  "41",    False),
        ("51010",  "تكلفة أدوية مُباعة",            "COGS — Drugs",                 "expense",  "5",     False),
        ("51020",  "تكلفة مستلزمات مُباعة",          "COGS — Medical Supplies",      "expense",  "5",     False),
        ("51030",  "أدوية منتهية الصلاحية (خسارة)",  "Expired Drug Loss",            "expense",  "5",     False),
        ("51040",  "أدوية مُرتجعة للمورّد",          "Drug Returns to Supplier",     "expense",  "5",     False),
        ("65040",  "تراخيص هيئة الغذاء والدواء",     "SFDA License Fees",            "expense",  "65",    False),
        ("65050",  "تخزين بارد (ثلاجات)",           "Cold Storage",                 "expense",  "65",    False),
    ],

    # ──── 🔧 WK — الورش والصيانة ────
    "workshop": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون قطع غيار",               "Spare Parts Inventory",        "asset",    "13",    False),
        ("13010",  "مخزون زيوت وسوائل",             "Oils & Fluids Inventory",      "asset",    "13",    False),
        ("13020",  "مخزون مواد استهلاكية",           "Consumables Inventory",        "asset",    "13",    False),
        ("16030",  "معدات ورشة",                   "Workshop Equipment",           "asset",    "16",    False),
        ("16040",  "رافعات ومعدات فحص",             "Lifts & Diagnostic Equipment", "asset",    "16",    False),
        ("18004",  "إهلاك متراكم — معدات ورشة",     "Accum. Depr. — Workshop Equip.","asset",   "18",    False),
        ("41010",  "إيرادات صيانة (عمالة)",          "Repair Labor Revenue",         "revenue",  "41",    False),
        ("41020",  "إيرادات بيع قطع غيار",          "Parts Sales Revenue",          "revenue",  "41",    False),
        ("41030",  "إيرادات فحص / تشخيص",           "Diagnostic Revenue",           "revenue",  "41",    False),
        ("51010",  "تكلفة قطع غيار مُستخدمة",       "Parts Cost Used",              "expense",  "5",     False),
        ("51020",  "تكلفة مواد استهلاكية",           "Consumables Cost",             "expense",  "5",     False),
        ("61030",  "أجور فنيين",                   "Technician Wages",             "expense",  "61",    False),
        ("65040",  "صيانة معدات الورشة",            "Workshop Equip. Maintenance",  "expense",  "65",    False),
        ("65050",  "أدوات وعدد",                   "Tools & Equipment",            "expense",  "65",    False),
    ],

    # ──── 🛒 EC — التجارة الإلكترونية ────
    "ecommerce": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون بضاعة",                  "Merchandise Inventory",        "asset",    "13",    False),
        ("13010",  "مخزون في مراكز التوزيع",        "Fulfillment Center Inventory", "asset",    "13",    False),
        ("13020",  "بضاعة بالطريق للعميل",          "Goods in Transit to Customer", "asset",    "13",    False),
        ("12030",  "ذمم بوابات الدفع",              "Payment Gateway Receivables",  "asset",    "12",    False),
        ("41010",  "مبيعات أونلاين",               "Online Sales",                 "revenue",  "41",    False),
        ("41020",  "مردودات ومسترجعات",             "Returns & Refunds",            "revenue",  "41",    False),
        ("41030",  "إيرادات شحن محصّلة",            "Shipping Revenue",             "revenue",  "41",    False),
        ("51010",  "تكلفة بضاعة مُباعة",            "COGS — E-commerce",            "expense",  "5",     False),
        ("64010",  "عمولات بوابات دفع",             "Payment Gateway Fees",         "expense",  "64",    False),
        ("64020",  "رسوم ماركت بليس",              "Marketplace Fees",             "expense",  "64",    False),
        ("65040",  "مصاريف شحن وتوصيل",            "Shipping & Delivery",          "expense",  "65",    False),
        ("65050",  "مصاريف تعبئة وتغليف",           "Packaging Expenses",           "expense",  "65",    False),
        ("65060",  "مصاريف مرتجعات Reverse",        "Reverse Logistics Cost",       "expense",  "65",    False),
    ],

    # ──── 🚛 LG — النقل واللوجستيات ────
    "logistics": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون وقود وزيوت",              "Fuel & Oil Inventory",         "asset",    "13",    False),
        ("13010",  "مخزون إطارات وقطع غيار",        "Tires & Spare Parts",          "asset",    "13",    False),
        ("16030",  "شاحنات ومركبات نقل",            "Trucks & Transport Vehicles",  "asset",    "16",    False),
        ("16040",  "معدات مستودعات (رافعات)",        "Warehouse Equipment (Forklifts)","asset",  "16",    False),
        ("18004",  "إهلاك متراكم — شاحنات",         "Accum. Depr. — Trucks",        "asset",    "18",    False),
        ("18005",  "إهلاك متراكم — معدات مستودعات",  "Accum. Depr. — Warehouse Eq.", "asset",    "18",    False),
        ("41010",  "إيرادات نقل / شحن",             "Freight Revenue",              "revenue",  "41",    False),
        ("41020",  "إيرادات تخزين",                "Warehousing Revenue",          "revenue",  "41",    False),
        ("41030",  "إيرادات تخليص جمركي",           "Customs Clearance Revenue",    "revenue",  "41",    False),
        ("41040",  "إيرادات توصيل ميل أخير",        "Last-mile Delivery Revenue",   "revenue",  "41",    False),
        ("51010",  "تكلفة وقود مباشر",              "Direct Fuel Cost",             "expense",  "5",     False),
        ("51020",  "تكلفة سائقين مباشر",            "Direct Driver Cost",           "expense",  "5",     False),
        ("51030",  "رسوم طرق وعبور",               "Toll & Transit Fees",          "expense",  "5",     False),
        ("61030",  "أجور سائقين",                  "Driver Wages",                 "expense",  "61",    False),
        ("65040",  "صيانة شاحنات",                 "Truck Maintenance",            "expense",  "65",    False),
        ("65050",  "تأمين مركبات",                 "Vehicle Insurance",            "expense",  "65",    False),
        ("65060",  "رسوم ترخيص مركبات",             "Vehicle License Fees",         "expense",  "65",    False),
        ("66020",  "إهلاك شاحنات",                 "Truck Depreciation",           "expense",  "66",    False),
    ],

    # ──── 🌾 AG — الزراعة والتجارة الزراعية ────
    "agriculture": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون محاصيل",                 "Crop Inventory",               "asset",    "13",    False),
        ("13010",  "مخزون أعلاف",                  "Feed Inventory",               "asset",    "13",    False),
        ("13020",  "مخزون بذور وأسمدة",             "Seeds & Fertilizer Inventory", "asset",    "13",    False),
        ("13030",  "أصول بيولوجية — مواشي",         "Biological Assets — Livestock","asset",    "13",    False),
        ("13040",  "أصول بيولوجية — دواجن",         "Biological Assets — Poultry",  "asset",    "13",    False),
        ("13050",  "أصول بيولوجية — أشجار مثمرة",   "Biological Assets — Trees",    "asset",    "13",    False),
        ("16030",  "معدات زراعية (جرارات)",          "Farm Equipment (Tractors)",    "asset",    "16",    False),
        ("16040",  "نظام ري",                     "Irrigation System",            "asset",    "16",    False),
        ("18004",  "إهلاك متراكم — معدات زراعية",   "Accum. Depr. — Farm Equip.",   "asset",    "18",    False),
        ("18005",  "إهلاك متراكم — نظام ري",        "Accum. Depr. — Irrigation",    "asset",    "18",    False),
        ("41010",  "إيرادات بيع محاصيل",            "Crop Sales Revenue",           "revenue",  "41",    False),
        ("41020",  "إيرادات بيع ماشية/دواجن",       "Livestock/Poultry Sales",      "revenue",  "41",    False),
        ("41030",  "إيرادات بيع ألبان/بيض",          "Dairy/Egg Sales",              "revenue",  "41",    False),
        ("41040",  "إيرادات أعلاف",                "Feed Sales Revenue",           "revenue",  "41",    False),
        ("42040",  "تغير القيمة العادلة — أصول بيولوجية", "Fair Value Change — Bio Assets","revenue","42",  False),
        ("51010",  "تكلفة بذور ومدخلات",            "Seeds & Input Cost",           "expense",  "5",     False),
        ("51020",  "تكلفة أعلاف",                  "Feed Cost",                    "expense",  "5",     False),
        ("51030",  "تكلفة أدوية بيطرية",            "Veterinary Medicine Cost",     "expense",  "5",     False),
        ("51040",  "تكلفة ري ومياه",               "Irrigation & Water Cost",      "expense",  "5",     False),
        ("51050",  "تكلفة حصاد / ذبح",              "Harvest / Slaughter Cost",     "expense",  "5",     False),
        ("61030",  "أجور عمال مزرعة",              "Farm Worker Wages",            "expense",  "61",    False),
        ("65040",  "صيانة معدات زراعية",            "Farm Equipment Maintenance",   "expense",  "65",    False),
        ("65050",  "تأمين محاصيل / حيوانات",        "Crop/Livestock Insurance",     "expense",  "65",    False),
        ("66020",  "إهلاك معدات زراعية",            "Farm Equipment Depreciation",  "expense",  "66",    False),
        ("66030",  "إطفاء أشجار مثمرة",             "Tree Amortization",            "expense",  "66",    False),
    ],

    # ──── 🌐 GN — نشاط عام ────
    "general": [
        ("13",     "مخزون",                       "Inventory",                    "asset",    "1",     True),
        ("13001",  "مخزون بضاعة",                  "Merchandise Inventory",        "asset",    "13",    False),
        ("41010",  "مبيعات متنوعة",                "Miscellaneous Sales",          "revenue",  "41",    False),
        ("41020",  "مردودات مبيعات",               "Sales Returns",                "revenue",  "41",    False),
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# دالة زرع شجرة الحسابات
# ═══════════════════════════════════════════════════════════════════════════════

def seed_industry_coa(db, industry_key: str, replace_existing: bool = False) -> dict:
    """
    يزرع الحسابات الأساسية + المتخصصة لنوع النشاط.
    
    Args:
        db: database session (company-specific)
        industry_key: مفتاح النشاط — يقبل كلا الصيغتين (RT/FB or retail/restaurant)
        replace_existing: إذا True يحذف كل الحسابات ويعيد إنشاءها (خطير)
    
    Returns:
        dict with counts: {"core": N, "industry": N, "skipped": N}
    """
    # Normalize: RT → retail, FB → restaurant, etc.
    industry_key = normalize_industry_key(industry_key)
    
    result = {"core": 0, "industry": 0, "skipped": 0, "errors": []}
    
    # Check if accounts already exist
    existing_count = db.execute(text("SELECT COUNT(*) FROM accounts")).scalar() or 0
    
    if existing_count > 0 and not replace_existing:
        # Add only missing industry-specific accounts
        industry_accts = INDUSTRY_ACCOUNTS.get(industry_key, INDUSTRY_ACCOUNTS.get("general", []))
        for acct in industry_accts:
            code, name_ar, name_en, acct_type, parent_code, is_header = acct
            exists = db.execute(
                text("SELECT 1 FROM accounts WHERE account_number = :code"),
                {"code": code}
            ).scalar()
            if exists:
                result["skipped"] += 1
                continue
            try:
                _insert_account(db, code, name_ar, name_en, acct_type, parent_code, is_header)
                result["industry"] += 1
            except Exception as e:
                result["errors"].append(f"{code}: {str(e)}")
        db.commit()
        # Link parents for newly inserted accounts
        _link_parents(db, industry_key)
        _ensure_default_coa_mappings(db)
        db.commit()
        return result
    
    if replace_existing and existing_count > 0:
        # Check if there are journal entries — don't delete if so
        je_count = db.execute(text("SELECT COUNT(*) FROM journal_entries")).scalar() or 0
        if je_count > 0:
            result["errors"].append("Cannot replace COA — journal entries exist")
            return result
        db.execute(text("DELETE FROM accounts"))
    
    # Insert core accounts
    for acct in CORE_ACCOUNTS:
        code, name_ar, name_en, acct_type, parent_code, is_header = acct
        try:
            _insert_account(db, code, name_ar, name_en, acct_type, parent_code, is_header)
            result["core"] += 1
        except Exception as e:
            result["errors"].append(f"Core {code}: {str(e)}")
    
    # Insert industry-specific accounts
    industry_accts = INDUSTRY_ACCOUNTS.get(industry_key, INDUSTRY_ACCOUNTS.get("general", []))
    for acct in industry_accts:
        code, name_ar, name_en, acct_type, parent_code, is_header = acct
        exists = db.execute(
            text("SELECT 1 FROM accounts WHERE account_number = :code"),
            {"code": code}
        ).scalar()
        if exists:
            result["skipped"] += 1
            continue
        try:
            _insert_account(db, code, name_ar, name_en, acct_type, parent_code, is_header)
            result["industry"] += 1
        except Exception as e:
            result["errors"].append(f"Industry {code}: {str(e)}")
    
    db.commit()
    
    # Now update parent_id references
    _link_parents(db, industry_key)
    _ensure_default_coa_mappings(db)
    db.commit()
    
    logger.info(f"COA seeded for '{industry_key}': core={result['core']}, industry={result['industry']}, skipped={result['skipped']}")
    return result


def _insert_account(db, code, name_ar, name_en, acct_type, parent_code, is_header):
    """Insert a single account into the accounts table.
    
    Maps to actual schema:
      account_number (UNIQUE NOT NULL) ← code
      account_code                     ← code
      name                             ← name_ar
      name_en                          ← name_en
      account_type                     ← acct_type
      is_header                        ← is_header (header = حساب رئيسي)
    """
    db.execute(text("""
        INSERT INTO accounts (account_number, account_code, name, name_en, account_type, is_header, is_active)
        VALUES (:code, :code, :name_ar, :name_en, :acct_type, :is_header, true)
        ON CONFLICT (account_number) DO NOTHING
    """), {
        "code": code,
        "name_ar": name_ar,
        "name_en": name_en,
        "acct_type": acct_type,
        "is_header": is_header,
    })


def _link_parents(db, industry_key: str = None):
    """Link parent_id based on parent_code in the template definitions."""
    # Only iterate core + the relevant industry's accounts
    accounts_to_link = list(CORE_ACCOUNTS)
    if industry_key:
        accounts_to_link += INDUSTRY_ACCOUNTS.get(industry_key, [])
    else:
        # Fallback: iterate all (legacy behavior)
        for accts in INDUSTRY_ACCOUNTS.values():
            accounts_to_link += accts
    
    for acct in accounts_to_link:
        code, _, _, _, parent_code, _ = acct
        if parent_code is None:
            continue
        try:
            db.execute(text("""
                UPDATE accounts 
                SET parent_id = (SELECT id FROM accounts WHERE account_number = :parent_code LIMIT 1)
                WHERE account_number = :code AND parent_id IS NULL
            """), {"code": code, "parent_code": parent_code})
        except Exception:
            pass


def _ensure_default_coa_mappings(db):
    """Ensure key tax account mappings exist after industry COA seeding."""
    mapping_codes = {
        "acc_map_vat_in": "15010",
        "acc_map_vat_out": "21040",
    }
    for key, account_number in mapping_codes.items():
        account_id = db.execute(
            text("SELECT id FROM accounts WHERE account_number = :num LIMIT 1"),
            {"num": account_number},
        ).scalar()
        if not account_id:
            continue
        db.execute(text("""
            INSERT INTO company_settings (setting_key, setting_value)
            VALUES (:key, :value)
            ON CONFLICT (setting_key) DO UPDATE
                SET setting_value = EXCLUDED.setting_value
        """), {"key": key, "value": str(account_id)})


def get_industry_coa_summary(industry_key: str) -> dict:
    """Return summary info about what COA a given industry would get."""
    industry_key = normalize_industry_key(industry_key)
    core_count = len(CORE_ACCOUNTS)
    industry_accts = INDUSTRY_ACCOUNTS.get(industry_key, [])
    industry_count = len(industry_accts)
    
    return {
        "industry_key": industry_key,
        "core_accounts": core_count,
        "industry_accounts": industry_count,
        "total_accounts": core_count + industry_count,
        "industry_account_codes": [a[0] for a in industry_accts],
    }
