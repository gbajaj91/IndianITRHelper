# SeFA
Python module to generate Indian ITR schedule FA under section A3 automatically

# How to run
Two brokers are supported, each with its own export file and `-m/--source-mode` value:

## ETRADE - Download `BenefitHistory.xlsx`
Use source mode `etrade_benefit_history` (the default) for ESPP/RSU grants and vests,
`etrade_holdings_bystatus` for a simpler "Sellable" holdings snapshot, or `etrade_gains_losses`
for a capital gains report (see below).
1. Click on `At Work` top menu bar
2. Click on `Holdings` top submenu bar
3. Click on `Benefit History` link either on `Employee Stock Purchase Plan (ESPP)` or `Restricted Stock (RS)`
4. Click on `Download` button which will open the popup.
5. Click on `Download Expanded` which will prompt you to download the `BenefitHistory.xlsx` file

### ETRADE capital gains - also download the Gains & Losses Expanded report
Source mode `etrade_gains_losses` computes capital gains for every RSU/ESPP lot in
`BenefitHistory.xlsx` (still passed via `-i`), using the Gains & Losses Expanded report (CSV or
XLSX) to look up each sold lot's actual sale price. Download it from:
1. `Accounts` -> `Gains & Losses`
2. Change the view/report to `Expanded` and set the date range to cover your full sale history
3. `Download` the report (CSV or XLSX both work) and pass its path via `--gains-losses-file`

## Charles Schwab - Download your transactions CSV
Use source mode `schwab_transactions` for a Schwab brokerage account (regular stock/ETF trades,
tracked with FIFO cost-basis matching against sells).
1. Log in to Schwab, go to your account's `History` tab
2. Select the date range you need and export as CSV (`Individual_..._Transactions_....csv`)

## Setup
The script requires Python 3.8 or higher. Please ensure that it is installed on your system. In newer versions of Python, you may encounter an [`externally-managed-environment`](https://peps.python.org/pep-0668/), so create and activate a [Python virtual environment](https://docs.python.org/3/library/venv.html#creating-virtual-environments) before installing the dependencies.

```sh
# From the repository root
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip3 install .
```

This installs all required dependencies (`pandas`, `openpyxl`, `yfinance`, `requests`).

## Run the script
With the virtual environment activated, run the script with the downloaded export file. A few
common combinations for each broker and report type:

```sh
# --- ETRADE ---

# Schedule FA (default source mode and report)
./run.py -i "<absolute_folder>/BenefitHistory.xlsx" -ay 2026

# Capital gains (LTCG/STCG) - needs both BenefitHistory.xlsx and the Gains & Losses
# Expanded report (CSV or XLSX)
./run.py -i "<absolute_folder>/BenefitHistory.xlsx" \
  -m etrade_gains_losses \
  --gains-losses-file "<absolute_folder>/G&L_Expanded.xlsx" \
  -r capital_gains -ay 2026

# --- Charles Schwab ---

# Schedule FA
./run.py -i "<absolute_folder>/Individual_..._Transactions_....csv" -m schwab_transactions -ay 2026

# Capital gains (LTCG/STCG)
./run.py -i "<absolute_folder>/Individual_..._Transactions_....csv" -m schwab_transactions \
  -r capital_gains -ay 2026

# Dividend income
./run.py -i "<absolute_folder>/Individual_..._Transactions_....csv" -m schwab_transactions \
  -r dividend_income -ay 2026
```

Detailed options are listed below
```txt
usage: run.py [-h] [-o OUTPUT_FOLDER] -i INPUT_EXCEL_FILE
              [-m {etrade_benefit_history,etrade_holdings_bystatus,schwab_transactions,etrade_gains_losses}]
              [--gains-losses-file GAINS_LOSSES_FILE]
              [-cal {calendar,financial}]
              [-r {fa,capital_gains,dividend_income}] -ay ASSESSMENT_YEAR [-v]
              [--skip-refresh]

This is a Python module to generate Indian ITR schedule FA under section A3 automatically

options:
  -h, --help            show this help message and exit
  -o OUTPUT_FOLDER, --output OUTPUT_FOLDER
                        Specify the absolute path of the output folder for JSON data, default = <current_folder_path_of_the_script>
  -i INPUT_EXCEL_FILE, --input INPUT_EXCEL_FILE
                        Specify the absolute path for the input file: benefit history
                        (`BenefitHistory.xlsx`) Excel file for etrade source modes (including
                        `etrade_gains_losses`, where it's the source of every trade), or the
                        transactions CSV export for `schwab_transactions`
  -m {etrade_benefit_history,etrade_holdings_bystatus,schwab_transactions,etrade_gains_losses}, --source-mode {etrade_benefit_history,etrade_holdings_bystatus,schwab_transactions,etrade_gains_losses}
                        Specify the source mode, default = etrade_benefit_history
  --gains-losses-file GAINS_LOSSES_FILE
                        Required with -m etrade_gains_losses: absolute path to ETRADE's Gains
                        & Losses Expanded report (CSV or XLSX). Every trade comes from -i's
                        BenefitHistory.xlsx; this file is only used to look up each sold lot's
                        actual sale quantity/price/date
  -cal {calendar,financial}, --calendar-mode {calendar,financial}
                        Specify the calendar period for consideration, default = calendar
  -r {fa,capital_gains,dividend_income}, --report {fa,capital_gains,dividend_income}
                        Specify the report to generate: 'fa' for Schedule FA section A3
                        (fa_entries.csv/transactions.csv), 'capital_gains' for an LTCG/STCG
                        capital gains report scoped to the financial year (capital_gains.csv),
                        or 'dividend_income' for gross dividends/tax withheld per ticker
                        scoped to the financial year (dividend_income.csv), default = fa
  -ay ASSESSMENT_YEAR, --assessment-year ASSESSMENT_YEAR
                        Current year of assessment year. For AY 2019-2020, input will be 2019. Input will be of type integer
  -v, --verbose         Enable the debug logs
  --skip-refresh        Skip refreshing historic share prices/rates from Yahoo Finance and use the
                        bundled/cached historic_data instead (useful when offline)
```

## Historic data auto-refresh
`run.py` refreshes both data sources automatically before generating the schedule, so you
do not need to run the refresh scripts yourself:

- **Share FMV** (`historic_data/shares/<ticker>/data.csv`) from Yahoo Finance via `yfinance`,
  for every ticker found in your input file (dynamically detected - no ticker is hardcoded).
- **RBI/FBIL reference rates** (`historic_data/rates/rbi/rates.xls`) from the FBIL benchmark
  via the public [Frankfurter API](https://frankfurter.dev), for every currency used by those
  tickers. FBIL data is available from 2018-07-10 onwards; only the refreshed currency pairs
  are replaced, other pairs already in the file are left untouched.

If a dependency is missing or there is no network, the run logs a warning and falls back to
the bundled data. Pass `--skip-refresh` to force the bundled data (useful when offline). You
can still run `refresh_historic_data.py` or `refresh_rbi_rates.py` manually.

## Output
Output is namespaced by source and report, as `<output>/<source-mode>/<report>/`, so different
combinations (e.g. an `fa` run and a `capital_gains` run, or two different brokers) never overwrite
each other. For example, `-m schwab_transactions -r fa` writes to `output/schwab_transactions/fa/`,
while `-m schwab_transactions -r capital_gains` writes to `output/schwab_transactions/capital_gains/`.

For the default `-r fa` report, two CSV files are generated covering every ticker found in your
input file:

- `transactions.csv` - the full workings (quantities, native purchase/peak/closing share prices,
  RBI rates applied, the resulting INR values, and realized gain/loss in both native currency and
  INR) for every lot, so you can validate the numbers before filing.
- `fa_entries.csv` - all tickers combined, in the exact column format Schedule FA section A3 expects,
  ready to upload as-is. For Schwab, "Total gross amount paid/credited with respect to the holding
  during the period" is real dividend income for that ticker within the calendar year (see Dividend
  income report below); other sources still show `0` there.

## Capital gains report
Pass `-r capital_gains` to generate `capital_gains.csv` instead of the Schedule FA report. This is
always scoped to the financial year (1-Apr to 31-Mar) regardless of `--calendar-mode`, since Indian
capital gains are always reported on a financial-year basis. Only sells (not merely-held lots) that
fall within that financial year are included - one row per sale, classified as `LTCG` (held more
than 24 months - the threshold for unlisted/foreign equity) or `STCG` otherwise, with the resulting
gain/loss in both native currency and INR.

**Limitation**: only sources that record each sale's own quantity/price can appear here - Schwab
(via its Buy/Sell rows), or ETRADE via `-m etrade_gains_losses` (every trade comes from
`BenefitHistory.xlsx`, matched to its actual sale price in the Gains & Losses Expanded report). The
default `etrade_benefit_history`/`etrade_holdings_bystatus` modes don't track per-sale detail at
all, so they can't produce this report. Even with `etrade_gains_losses`, a lot that's sold per
BenefitHistory.xlsx but has no matching row in the Gains & Losses Expanded file is skipped (logged,
not silently dropped) - e.g. if the export's date range doesn't cover that sale.

## Dividend income report
Pass `-r dividend_income` to generate `dividend_income.csv` - gross dividends and tax withheld
(e.g. NRA tax withholding), one row per ticker, scoped to the financial year like capital gains.
Dividend and tax-withholding postings aren't matched to each other by date (a tax posting isn't
guaranteed to land on the same date as the dividend it applies to), so both are summed per ticker
over the whole financial year rather than paired per payment.

Currently Schwab-only (dividend/tax rows in the transactions CSV - any `Action` containing "Div",
and `NRA Tax Adj` rows with a Symbol). A ticker with dividend income but no purchase record in the
file (e.g. the original purchase predates the exported date range) still gets reported rather than
silently dropped - watch the console for a "No purchase record found" message when this happens.

# Limitations
- `BenefitHistory.xlsx` (etrade), ETRADE's Gains & Losses Expanded report (CSV or XLSX), and the
  Schwab transactions CSV are the only supported input formats.
- Sell handling differs by source: Schwab sells are matched FIFO against buys and reduce the
  reported holding. For `etrade_benefit_history`/`etrade_holdings_bystatus`, RSU releases have no
  sell tracking at all (the RSU sheet doesn't record sales), and ESPP purchases only know a lot was
  fully sold as of some date, not with enough detail for the capital gains report. `etrade_gains_losses`
  fills this gap by matching each BenefitHistory lot to its actual sale in the Gains & Losses
  Expanded report - see the Capital gains report limitation above for what happens when a lot has
  no matching row there.
- This script is only tested under Mac.
- Currently script works based on `historic_data`, which is generated locally (git-ignored) by the
  auto-refresh described above - share FMV in `historic_data/shares/<ticker>/data.csv` and RBI/FBIL
  rates in `historic_data/rates/rbi/rates.xls`. Use `--skip-refresh` if you'd rather work offline
  against a previous run's cached data.
- **TODO**: Org info/currency per ticker is fetched dynamically from yfinance, but the Schedule FA "Country Code" mapping (`utils/ticker_mapping.py`'s `REGION_INFO`) currently only covers `US`. A ticker whose company/fund is based elsewhere will fail fast with a clear error until that region's ITD numeric code is added to the table.

# Author
[Atul Gupta](https://github.com/atulgpt)

# Disclaimer
In case of any issues, please create a bug report. Also, do not entirely depend on the script for ITR filing. Do your own due diligence before filing your ITR.