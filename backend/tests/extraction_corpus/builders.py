"""Synthetic extraction fixtures shaped like the files brokers and property
managers actually send, with the hostile formatting the audit found in the
wild baked in on purpose:

- Yardi-Voyager-style rent roll: merged title banner rows above the headers,
  text unit numbers ("A-101"), a literal VACANT resident, a blank vacant row,
  and a mid-table subtotal row.
- Yardi-style T-12: twelve month columns plus a trailing annual total,
  parenthesized-negative strings, subtotal/NOI rows, and lines that match no
  standard category (Pest Control, RUBS Income).
- RealPage-style rent roll: different header vocabulary and an explicit
  status column.
- Broker-OM-style PDF: a two-page ruled rent-roll table with a repeated
  header row (exercises the multi-page merge fix).
"""

import openpyxl
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

MONTH_HEADERS = [
    "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026",
    "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026", "Dec 2026",
]


def build_yardi_rent_roll(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rent Roll"
    ws.merge_cells("A1:H1")
    ws["A1"] = "Maple Court Apartments"
    ws.merge_cells("A2:H2")
    ws["A2"] = "Rent Roll as of 06/30/2026"
    headers = ["Unit", "Unit Type", "SQFT", "Resident", "Market Rent", "Actual Rent", "Move In", "Lease Expiration"]
    ws.append([])
    ws.append(headers)
    rows = [
        ["A-101", "1BR/1BA", 750, "Alice Johnson", 1500, 1450, "05/01/2024", "04/30/2026"],
        ["A-102", "1BR/1BA", 750, "Bob Smith", 1500, 1480, "01/15/2025", "01/14/2027"],
        ["A-103", "1BR/1BA", 750, "VACANT", 1500, None, None, None],
        ["Total 1BR/1BA", None, 2250, None, 4500, 2930, None, None],  # subtotal row
        ["B-201", "2BR/2BA", 1100, "Carol Davis", 2100, 2050, "07/01/2023", "06/30/2026"],
        ["B-202", "2BR/2BA", 1100, "Dan Edwards", 2100, 2080, "03/01/2025", "02/28/2027"],
        ["B-203", "2BR/2BA", 1100, None, 2100, None, None, None],  # blank vacant row
        ["Total 2BR/2BA", None, 3300, None, 6300, 4130, None, None],
    ]
    for row in rows:
        ws.append(row)
    wb.save(path)


def build_yardi_t12(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "T12"
    ws.merge_cells("A1:N1")
    ws["A1"] = "Maple Court Apartments — Trailing 12 Statement"
    ws.append(["Account"] + MONTH_HEADERS + ["Annual Total"])

    def line(label, monthly, total=None, as_text=False):
        cells = [label]
        for _ in range(12):
            cells.append(f"({abs(monthly):,})" if as_text and monthly < 0 else monthly)
        cells.append(
            f"({abs(monthly) * 12:,})" if as_text and monthly < 0 else (total if total is not None else monthly * 12)
        )
        ws.append(cells)

    line("Gross Potential Rent", 50_000)
    line("Vacancy Loss", -2_500, as_text=True)  # parenthesized-negative strings
    line("Bad Debt", -400, as_text=True)
    line("RUBS Income", 1_200)  # matches no standard alias -> unclassified
    line("Total Income", 48_300)
    line("Real Estate Taxes", 5_000)
    line("Insurance", 1_500)
    line("Utilities", 2_000)
    line("Repairs and Maintenance", 1_800)
    line("Payroll", 2_500)
    line("Management Fees", 1_600)
    line("Office Expense", 700)
    line("Reserve for Replacement", 500)
    line("Pest Control", 250)  # unclassified expense line
    line("Total Operating Expenses", 15_850)
    line("Net Operating Income", 32_450)
    wb.save(path)


def build_realpage_rent_roll(path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Unit Availability"
    headers = ["Bldg/Unit", "Floorplan", "SQFT", "Name", "Lease Rent", "Market + Addl.", "Move-In", "Lease End", "Status"]
    ws.append(headers)
    rows = [
        ["01-101", "A1", 720, "Eve Foster", 1395, 1425, "2024-09-01", "2026-08-31", "Occupied"],
        ["01-102", "A1", 720, "Frank Garcia", 1410, 1425, "2025-02-01", "2027-01-31", "Occupied"],
        ["01-103", "A1", 720, None, None, 1425, None, None, "Vacant-Ready"],
        ["02-201", "B2", 1050, "Grace Harris", 1975, 2010, "2023-11-15", "2026-11-14", "Occupied"],
        ["02-202", "B2", 1050, "Henry Irving", 1990, 2010, "2025-05-01", "2026-04-30", "Notice"],
    ]
    for row in rows:
        ws.append(row)
    wb.save(path)


def build_commercial_rent_roll(path) -> None:
    """Office/retail-style commercial roll: suite/tenant/SF/monthly rent/
    lease type/dates, mixed date formats, one vacant suite. Feeds the H1
    lease-proposal path (rent converts to $psf/yr; lease types map to
    recovery structures; the vacant suite is skipped with a warning)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rent Roll"
    headers = ["Suite", "Tenant", "SF", "Monthly Rent", "Lease Type", "Lease Start", "Lease Expiration"]
    ws.append(headers)
    rows = [
        ["100", "Blue Bagel LLC", 2400, 6000, "NNN", "01/01/2024", "12/31/2028"],
        ["110", "Verde Yoga", 1800, 3900, "Gross", "06/01/2025", "05/31/2030"],
        ["120", "Corner Dental", 3000, 8250, "Modified Gross", "2023-03-01", "2033-02-28"],
        ["130", "VACANT", 1200, None, None, None, None],
    ]
    for row in rows:
        ws.append(row)
    wb.save(path)


def build_broker_om_pdf(path) -> None:
    styles = getSampleStyleSheet()
    header = ["Unit", "Tenant", "SF", "Rent"]
    page1_rows = [header] + [
        ["101", "Ivy Café LLC", "1,200", "3,600"],
        ["102", "Jasper Books", "950", "2,375"],
        ["103", "Kite Fitness", "2,100", "5,250"],
    ]
    page2_rows = [header] + [  # repeated header on the continuation page
        ["104", "Luna Salon", "800", "2,200"],
        ["105", "", "1,500", ""],  # vacant suite
    ]
    grid_style = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]
    )
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    doc.build(
        [
            Paragraph("Offering Memorandum — Shoppes at Kite Hill", styles["Title"]),
            Paragraph("Confidential. Rent roll as of June 2026.", styles["Normal"]),
            Table(page1_rows, style=grid_style),
            PageBreak(),
            Table(page2_rows, style=grid_style),
        ]
    )
