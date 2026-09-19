// Plain-language definitions for Deal Inputs fields (roadmap #15): what the
// number is, its unit/basis, and how the built-in engine uses it. Kept here
// rather than in input_schema.json so the schema stays the engine contract.
// Every statement matches the engine's conventions (DECISIONS.md).

export const FIELD_HELP: Record<string, string> = {
  // Deal basics
  dealType: 'Acquisition (buy an existing property) or development (build it). Decides which cost, timeline and financing inputs apply.',
  propertyType: 'Sets which income sections show (unit mix, rent roll, per-SF rent…).',

  // Financing
  ltvOrLtc:
    'Maximum loan as a share of value (acquisitions: of purchase price) or of total development cost including capitalized interest and loan fees (developments). 0 = all equity.',
  loanAmount: 'Optional fixed loan amount (acquisitions). Overrides the constraint-based sizing; a warning shows if it exceeds the sized proceeds.',
  interestRate: 'Annual interest rate on the loan (fixed-rate mode). Construction interest accrues monthly and is capitalized.',
  rateMode: 'Fixed rate, or floating (index + spread, with an optional floor and rate cap).',
  currentIndexPct: 'Floating mode: today’s index rate (e.g. SOFR), annual %. Used until the first forward-curve point.',
  spreadBps: 'Floating mode: the lender’s margin over the index, in basis points (250 = 2.50%).',
  floorPct: 'Floating mode: the lowest index rate the loan charges, annual %.',
  forwardCurve: 'Floating mode: expected index by month. Between points the index is interpolated.',
  rateCapStrikePct: 'Rate cap: the index level above which the cap pays; DSCR at the strike is reported.',
  rateCapTermMonths: 'Rate cap: how long the cap lasts, in months.',
  rateCapPremium: 'Rate cap: upfront cost, paid by equity at closing.',
  amortYears: 'Amortization period in years (after any interest-only months). 30 = standard; 0 = interest-only for the whole loan.',
  loanTermYears:
    'Loan maturity in years (from closing; for developments from the permanent takeout). If it ends before the exit, the balloon is refinanced. Blank = no maturity.',
  ioMonths: 'Interest-only months at the start of the loan before amortization begins.',
  originationFeePct: 'Lender fee as a % of the loan amount (construction: of the full commitment), paid or capitalized at funding.',
  monthsOfTaxesAndInsurance: 'Tax and insurance escrow funded at closing, in months of those expenses; released at exit.',
  dscrConstraint:
    'Loan sizing floor: minimum debt service coverage (NOI ÷ debt service), e.g. 1.25. The loan is sized so it isn’t breached. 0 = no DSCR constraint.',
  debtYieldConstraint: 'Loan sizing floor: minimum NOI ÷ loan amount, e.g. 8%. 0 = no debt-yield constraint.',
  sizingNoiBasis: 'Which NOI sizes the loan: in-place (today), stabilized (the NOI input or modeled stabilized), or the model’s own underwritten NOI.',
  refiRateSpreadPct: 'Rate on a refinance or permanent takeout, as a spread over the current loan rate (annual %; may be negative).',
  refiCostsPct: 'Costs of a refinance or permanent takeout, as a % of the new loan, paid by equity.',
  permanentLtvPct: 'Developments: maximum LTV for the permanent loan at stabilization, if different from the construction LTC. Blank = same as LTC.',
  juniorTrancheKind: 'Optional mezzanine loan or preferred equity behind the senior loan.',
  juniorAmount: 'Junior tranche size in dollars. 0 = fill combined leverage to the % below.',
  juniorFillToLtcPct: 'Size the junior tranche so senior + junior reach this share of cost.',
  juniorRatePct: 'Annual rate on the junior tranche.',
  juniorPayMode: 'Current: interest paid monthly from cash flow. Accrued: interest compounds and is repaid at exit.',
  juniorOriginationFeePct: 'Junior tranche fee as a % of its amount.',

  // Equity
  lpSplitPct: 'Limited partners’ share of equity contributed (and of distributions before any promote).',
  gpSplitPct: 'Sponsor’s (GP) share of equity contributed.',
  preferredReturnPct: 'Annual preferred return owed to investors before any promote, compounded monthly.',
  waterfallStyle:
    'European: promote only after LPs reach each IRR hurdle on the whole fund. American (deal-by-deal): tier 1’s promote starts once the pref and capital are returned.',
  assetMgmtFeePct: 'Partnership asset-management fee, as a % of the basis chosen below; paid before distributions.',
  assetMgmtFeeBasis: 'What the asset-management fee is a % of: effective gross income, or committed equity.',
  catchUpPct: 'GP catch-up: share of distributions paid to the GP after the pref until it reaches its promote share of profit.',
  waterfallTiers: 'Promote tiers: above each LP IRR hurdle, distributions split LP/GP at that tier’s percentages.',

  // Income
  grossPotentialRent: 'Annual rent if 100% leased at today’s rents (year 1, before vacancy). A unit mix or rent roll, when entered, replaces it.',
  vacancyPct: 'Share of gross potential rent lost to vacancy, annual %. Lease-by-lease deals use rollover downtime instead (see General Vacancy there).',
  creditLossPct: 'Share of collected rent lost to non-payment (bad debt), applied after vacancy.',
  otherIncome: 'Annual income besides rent (parking, fees…), year 1 dollars; grows with rent.',

  // Expenses
  realEstateTaxes: 'Annual property taxes, year 1 dollars; grow at the expense growth rate.',
  insurance: 'Annual insurance, year 1 dollars.',
  utilities: 'Annual owner-paid utilities, year 1 dollars.',
  repairsMaintenance: 'Annual repairs and maintenance, year 1 dollars.',
  payroll: 'Annual on-site payroll, year 1 dollars.',
  generalAdmin: 'Annual general and administrative costs, year 1 dollars.',
  managementFeePct: 'Property management fee as a % of effective gross income (EGI).',
  replacementReserves: 'Annual capital reserve in dollars (for roofs, HVAC…).',
  replacementReservesPerUnit: 'Annual capital reserve per unit, in dollars.',
  replacementReservesPsf: 'Annual capital reserve per square foot, in dollars.',
  reservesConvention:
    'Below NOI (default): reserves are a capital cost after NOI. Above NOI (underwritten): they reduce NOI, so they also lower exit value, DSCR and sizing.',
  opexLineItems: 'Detailed expense lines. Each amount is annual dollars, $ per unit, $ per SF, or % of EGI depending on its basis.',
  opexAllocationBasis: 'Mixed-use: how shared expenses split between residential and commercial.',
  nonAdValoremTaxes: 'Fixed assessments not based on property value (e.g. CDD fees), annual dollars.',
  nonAdValoremGrowthPct: 'Annual growth of those assessments.',
  nonAdValoremRecoverable: 'Whether commercial tenants reimburse those assessments.',
  useReassessedTaxes: 'Replace the tax input with a reassessment on the purchase price (millage × assessment ratio).',
  millageRatePct: 'Tax rate as a % of assessed value.',
  assessmentRatio: 'Share of market value that is assessed for taxes.',
  reassessedTaxGrowthPct: 'Annual growth of reassessed taxes (can differ from other expenses, e.g. a statutory cap).',

  // Renovation
  renovationProgram:
    'Value-add renovations by unit type: units renovated, cost per unit, monthly rent premium, downtime per unit and pace. Renovated units earn no rent while offline.',
  renoFundingSource: 'Renovation budget funded by equity at closing, or from operating cash as it is spent.',

  // Growth
  rentGrowthMode: 'Flat: no rent growth. Per year: rents step up once a year at the rate below.',
  rentGrowthPct: 'Annual rent growth, applied on each anniversary (developments: from delivery unless set to grow from closing).',
  expenseGrowthMode: 'Flat: no expense growth. Per year: expenses step up once a year.',
  expenseGrowthPct: 'Annual expense growth, applied on each anniversary.',

  // Exit
  holdPeriodYears: 'Years from closing to sale.',
  analysisStartDate:
    'Calendar date of closing. Lease start and expiry dates are placed relative to it. Blank = 1 January 2026.',
  exitCapRatePct: 'Cap rate a buyer pays at exit: sale value = next 12 months’ NOI ÷ this rate (or trailing NOI if chosen below).',
  costOfSalePct: 'Broker and closing costs at sale, as a % of the sale price.',
  exitNoiBasis: 'Forward (default): value the exit on the next 12 months’ NOI. Trailing: on the last 12 months of the hold.',
  prepaymentPenaltyPct: 'Cost of repaying the loan at sale (step-down, or an approximation of defeasance / yield maintenance), as a % of the balance repaid.',
  discountRatePct: 'Annual rate used to discount cash flows for NPV and profitability index.',
  irrConvention: 'Periodic monthly (default): monthly IRR annualized. XIRR: Excel’s date-based IRR.',
  residentialExitCapPct: 'Mixed-use: exit cap for the residential component (with the commercial cap, values each separately).',
  commercialExitCapPct: 'Mixed-use: exit cap for the commercial component.',

  // Acquisition
  purchasePrice: 'Contract price for the property.',
  closingCostsPct: 'Buyer’s closing costs (title, legal, transfer taxes…) as a % of price.',
  dueDiligenceCosts: 'Inspections, reports and other diligence, in dollars.',
  acquisitionFeePct: 'Sponsor’s acquisition fee as a % of price.',
  dayOneCapex: 'Capital work funded at closing, in dollars.',
  inPlaceNoi: 'Optional: today’s actual NOI, for going-in cap rate and in-place loan sizing. Blank = the model’s year-1 NOI.',
  stabilizedNoi: 'Optional: NOI once stabilized, used for sizing on the stabilized basis. Blank = the model’s own stabilized NOI.',

  // Development
  landCost: 'Land purchase price, paid at closing.',
  hardCosts: 'Construction (bricks and mortar) budget, in dollars; spent over the build on an S-curve or your draw schedule.',
  softCosts: 'Design, permits, legal and other soft costs, in dollars; spent evenly over the build.',
  contingencyPct: 'Contingency as a % of hard + soft costs.',
  developerFeePct: 'Developer fee as a % of hard + soft + contingency.',
  constructionMonths: 'Length of the build in months. Blank or 0 = no construction period.',
  growDuringConstruction: 'Off (default): rents and expenses start growing at delivery. On: they grow from closing.',
  leaseUpMonths: 'Months after completion to reach stabilized occupancy; occupancy ramps up over this period.',
  stabilizationMonth: 'Optional: the month the property counts as stabilized. Blank = end of construction + lease-up.',
  constructionDrawSchedule: 'Optional monthly spend. The amounts set the timing shape; the total always equals the non-land budget.',

  // Multifamily
  unitMix: 'Units by type with in-place and market rents (monthly $ per unit). Replaces gross potential rent when entered.',
  lossToLeaseCapturePct: 'Share of the in-place-to-market rent gap captured when a unit turns over.',
  lossToLeasePct: 'Flat reduction to unit-mix rent for below-market leases, as a %.',
  concessionsPct: 'Rent given up to concessions (free months, discounts), as a % of unit-mix rent.',
  parkingIncome: 'Annual parking income, year 1 dollars.',
  rubsIncome: 'Annual utility reimbursements from residents (RUBS), year 1 dollars.',
  otherFeeIncome: 'Annual fee income (pets, applications, late fees…), year 1 dollars.',

  // Commercial rent roll
  commercialLeases: 'Lease-by-lease rent roll: area, dates, rent per SF per year, escalations, recoveries and free rent. Name a leasing profile to roll a lease over on that profile instead of the deal assumptions.',
  keys: 'Number of guest rooms (keys).',
  adr: 'Average daily rate: rooms revenue per occupied room-night, in today\'s dollars. Grows at the rent growth rate.',
  occupancyPct: 'Share of available room-nights sold at stabilization. Rooms revenue = keys × ADR × occupancy × 365.',
  fnbRevenue: 'Food & beverage revenue per year at stabilized occupancy; scales with occupancy during a ramp.',
  otherRevenue: 'Other operated departments and miscellaneous revenue per year (parking, spa, resort fees) at stabilized occupancy.',
  departmentalExpenseRatioPct: 'Departmental expenses (rooms, F&B and other operated departments) as a share of total revenue.',
  undistributedExpenseRatioPct: 'Undistributed operating expenses (admin, sales & marketing, property operations, utilities) as a share of total revenue.',
  ffeReservePct: 'Furniture, fixtures & equipment reserve as a share of total revenue. Deducted before NOI, as lenders and appraisers do.',
  franchiseFeePct: 'Brand franchise fees (royalty, marketing, reservations) as a share of rooms revenue.',
  managementFeeHotelPct: 'Hotel operator base management fee as a share of total revenue.',
  homeCount: 'Number of homes (or lots) in the project.',
  buildCostPerHome: 'Vertical construction cost per home, spent over the months it takes to build one. Site work goes in Hard Costs.',
  absorptionPerMonth: 'Homes that close each month once sales begin (for-sale), or the lease-up pace (rental).',
  isForSale: 'On: homes are built and sold, and the deal returns the sales margin. Off: homes are held as rentals.',
  salePricePerHome: 'Sale price per home in today\'s dollars. Entering it switches Compute to the build-to-sell model.',
  rentPerHome: 'Monthly rent per home; gross potential rent = homes × rent × 12.',
  homeBuildMonths: 'Months to build one home. Each home\'s construction cost is spent over these months, ending at its closing.',
  homePriceGrowthPct: 'Annual growth in home prices from the first closing.',
  marketLeasingProfiles: 'Rollover assumptions per space type (anchor, inline, office floor…). A lease uses the profile named in its Leasing Profile column; blank cells here keep the deal assumptions.',
  buildingRsf:
    "The building's total rentable SF. It's the denominator for each tenant's pro-rata share of recoveries and for occupancy. Blank = the sum of the listed leases' SF (then there's no vacant space to count).",
  renewalProbability: 'Chance a tenant renews at expiry. Rollover income blends renewal and re-let outcomes by this probability.',
  downtimeMonths: 'Months a space sits empty before a new tenant (re-let path only).',
  freeRentMonthsNew: 'Free rent for a new tenant after downtime, in months (base rent only).',
  freeRentMonthsRenewal: 'Free rent on a renewal, in months (base rent only).',
  leaseGeneralVacancyPct:
    'Extra vacancy on top of rollover downtime, as a % of rent + recoveries. Only tops up months where downtime is lower (ARGUS method).',
  marketRentPsf: 'Market rent for re-leased space, $ per SF per year.',
  marketRentGrowthPct: 'Annual growth of market rent.',
  newTermYears: 'Length of each new or renewal lease after an expiry, in years.',
  tiNewPsf: 'Tenant improvements for a new lease, $ per SF.',
  tiRenewalPsf: 'Tenant improvements for a renewal, $ per SF.',
  lcNewPct: 'Leasing commissions on a new lease, as a % of total lease rent.',
  lcRenewalPct: 'Leasing commissions on a renewal, as a % of total lease rent.',
  renewalRentPsfDiscountPct: 'Renewal rent as a multiple of market rent (1.0 = at market, 0.95 = 5% below).',
  grossUpToPct: 'Base-year leases: gross variable expenses up to this occupancy before comparing with the base year.',
  reletCapitalAtCommencement: 'Pay re-let TI/LC when the new tenant starts (after downtime) instead of at expiry.',
  adminFeePct: 'Administrative markup on recoverable expenses billed to tenants.',
  mgmtFeeRecoverable: 'Whether tenants reimburse the management fee.',
  mgmtRecoveryCapPct: 'Cap on the recoverable management fee, as a % of pre-recovery EGI.',

  // Per-SF income
  rentableSf: 'Rentable square feet.',
  clearHeightFt: 'Warehouse clear height in feet — descriptive; not used in the calculation.',
  rentPsf: 'Rent in $ per SF per year.',
  nnnRecoveriesPsf: 'Expense reimbursements from tenants, $ per SF per year.',
  officeRentableSf: 'Office rentable square feet.',
  officeRentPsf: 'Office rent in $ per SF per year.',
  parkingIncomeOffice: 'Annual parking income, year 1 dollars.',
}
