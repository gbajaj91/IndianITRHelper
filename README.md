# SeFA
Python module to generate Indian ITR schedule FA under section A3 automatically

# How to run
## Download `BenefitHistory.xlsx` from `ETRADE`
1. Click on `At Work` top menu bar
2. Click on `Holdings` top submenu bar
3. Click on `Benefit History` link either on `Employee Stock Purchase Plan (ESPP)` or `Restricted Stock (RS)`
4. Click on `Download` button which will open the popup.
5. Click on `Download Expanded` which will prompt you to download the `BenefitHistory.xlsx` file

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
With the virtual environment activated, run the script with the downloaded `BenefitHistory.xlsx`:
```sh
./run.py -i "<absolute_folder_of_benefit_history_file>/BenefitHistory.xlsx" -ay 2023
```

Detailed options are listed below
```txt
usage: run.py [-h] [-o OUTPUT_FOLDER] -i INPUT_EXCEL_FILE [-m {etrade_benefit_history}] [-cal {calendar,financial}] -ay ASSESSMENT_YEAR [-v]

This is a Python module to generate Indian ITR schedule FA under section A3 automatically

options:
  -h, --help            show this help message and exit
  -o OUTPUT_FOLDER, --output OUTPUT_FOLDER
                        Specify the absolute path of the output folder for JSON data, default = <current_folder_path_of_the_script>
  -i INPUT_EXCEL_FILE, --input INPUT_EXCEL_FILE
                        Specify the absolute path for input benefit history(BenefitHistory.xlsx) Excel file
  -m {etrade_benefit_history}, --source-mode {etrade_benefit_history}
                        Specify the source mode. Currently, only benefit history from etrade is supported, default = etrade_benefit_history
  -cal {calendar,financial}, --calendar-mode {calendar,financial}
                        Specify the calendar period for consideration, default = calendar
  -r {fa,capital_gains}, --report {fa,capital_gains}
                        Specify the report to generate: 'fa' for Schedule FA section A3
                        (fa_entries.csv/transactions.csv), or 'capital_gains' for an LTCG/STCG
                        capital gains report scoped to the financial year (capital_gains.csv),
                        default = fa
  -ay ASSESSMENT_YEAR, --assessment-year ASSESSMENT_YEAR
                        Current year of assessment year. For AY 2019-2020, input will be 2019. Input will be of type integer
  -v, --verbose         Enable the debug logs
```

## Historic data auto-refresh
`run.py` refreshes both data sources automatically before generating the schedule, so you
do not need to run the refresh scripts yourself:

- **Share FMV** (`historic_data/shares/<ticker>/data.csv`) from Yahoo Finance via `yfinance`,
  for every ticker in your `BenefitHistory.xlsx`.
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
  ready to upload as-is.

## Capital gains report
Pass `-r capital_gains` to generate `capital_gains.csv` instead of the Schedule FA report. This is
always scoped to the financial year (1-Apr to 31-Mar) regardless of `--calendar-mode`, since Indian
capital gains are always reported on a financial-year basis. Only sells (not merely-held lots) that
fall within that financial year are included - one row per sale, classified as `LTCG` (held more
than 24 months - the threshold for unlisted/foreign equity) or `STCG` otherwise, with the resulting
gain/loss in both native currency and INR.

**Limitation**: only sources that record each sale's own quantity/price (currently just Schwab, via
its Buy/Sell rows) can appear here. ESPP purchases only record that a lot was fully sold as of some
date, not the quantity/price of that sale, so they're skipped (logged, not silently dropped) until
that data is available.

# Limitations
- Only parsing data from `BenefitHistory.xlsx` is supported.
-  If you have sold any shares, the script will not adjust those. You have to subtract the `BenefitHistory.xlsx` manually
-  This script is only tested under Mac, with a single `adbe` ticker with `calendar` `--calendar-mode` mode
-  Currently script works based on `historic_data`. Share FMV values is  present in [data.csv][data csv file]([ref][data csv ref])(check the first and last data in the file) and [rates.xls][SBI rates]([ref][SBI rates ref]) for RBI rate conversion
-  **TODO**: Org info/currency per ticker is fetched dynamically from yfinance, but the Schedule FA "Country Code" mapping (`utils/ticker_mapping.py`'s `COUNTRY_CODE_BY_NAME`) currently only covers `United States`. A ticker whose company is headquartered elsewhere will fail fast with a clear error until that country's ITD numeric code is added to the table.

# Author
[Atul Gupta](https://github.com/atulgpt)

# Disclaimer
In case of any issues, please create a bug report. Also, do not entirely depend on the script for ITR filing. Do your own due diligence before filing your ITR.


 [data csv file]: https://github.com/atulgpt/SeFA/blob/main/historic_data/shares/adbe/data.csv
 [data csv ref]: https://finance.yahoo.com/quote/ADBE/history/
 [SBI rates]: https://github.com/atulgpt/SeFA/blob/main/historic_data/rates/rbi/rates.xls
 [SBI rates ref]: https://www.fbil.org.in/#/home