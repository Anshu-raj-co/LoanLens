# LoanLens User Guide

LoanLens is a **prototype** that gives a quick, explained pre-eligibility check for a loan. It estimates whether an application looks like those that were **approved** in a public, synthetic dataset. It is **not a lending decision**, it does **not** predict whether a loan would be repaid (default), and every policy limit it uses is an **illustrative placeholder** until replaced by a lender's real credit policy.

Start the app with `streamlit run app/Home.py` (setup: see README.md) and open the address it prints, usually http://localhost:8501. Use the sidebar to move between pages.

---

## Part 1: For customers (Check My Eligibility)

### What you need

| Field | What to enter |
|---|---|
| CIBIL score | Your credit score from CIBIL, 300 to 900. |
| Annual income (Rs) | Total yearly income before tax. Must be more than 0. |
| Loan amount requested (Rs) | The amount you want to borrow. Must be more than 0. |
| Loan term (years) | Repayment period in whole years. |
| Residential property (Rs) | Value of homes or residential land you own. 0 if none. |
| Commercial property (Rs) | Value of shops, offices or commercial land. 0 if none. |
| Luxury assets (Rs) | Vehicles, jewellery and similar. 0 if none. |
| Bank balances and deposits (Rs) | Savings, fixed deposits and investments. 0 if none. |

Under each amount the app repeats what you typed in Indian grouping (for example "= Rs 1,50,00,000") so you can check the number of zeros. Then press **Check eligibility**.

**Your privacy:** nothing you enter on this page is stored or logged. The result is calculated in memory and discarded when you leave.

### Reading your result

- **The banner:** a green **Approved** or a red **Rejected** with a one-line summary ("Likely to be approved", or "Likely to be rejected (a policy rule was not met)").
- **Approval likelihood:** for example "96% - Very likely". It never shows 0% or 100% (">99%" / "<1%" instead). The words mean: Very likely (85% or more), Likely (65-85%), Borderline (35-65%), Unlikely (15-35%), Very unlikely (under 15%). It is a *model score on synthetic data - indicative only*.
- **Borderline - manual review recommended** (amber): the case is close to call; see below.
- **Why** (red-edged cards, rejections only): the main reasons, each with *your value*, a *benchmark* and a suggestion. A failed policy rule always comes first.
- **What would likely change this** (blue card): for example "Raising your CIBIL score to about 560 would likely change the result." It only ever suggests a higher CIBIL score or a smaller loan, and it is an estimate, never a guarantee.
- **What is working in your favour** (green-edged cards, approvals only).
- **Warnings** (amber): for example values outside the range the model has seen, or an EMI that looks high at the assumed 10% interest rate.
- **Policy checks** (click to open): each rule marked with the word "Passed" (green), "Failed" (red) or "Advisory" (amber, advisory only).

### How the borderline flag works

A result is marked **borderline - manual review recommended** when it is too close to call. Your result is still Approved or Rejected; the flag only suggests that a person should take a second look. It appears in two situations:

1. **The model score is close to the cut-off:** between 40% and 60%, and no enforced policy rule was failed.
2. **Your CIBIL score is close to the minimum:** within 25 points of 550 on either side (525 to 575). For example, a CIBIL score of 540 is rejected by the CIBIL rule but flagged, because a small difference in the score could change the outcome.

**Why a CIBIL score near the minimum is *not* flagged when another rule also failed:** if the application also breaks a different enforced rule, for example a loan term longer than 20 years or a loan more than 4 times the annual income, it would be rejected even with a better CIBIL score. Reviewing the CIBIL score by hand could not change that, so calling it borderline would be misleading.

The word "Borderline" in the likelihood band (35-65%) is only a description of the score; the amber pill is what means *manual review recommended*. All of these numbers are placeholders in `config/policy.yaml`.

### Common messages

| Message | What to do |
|---|---|
| "Please correct the following and try again" | A field is missing or impossible (for example income of 0). Fix the listed fields. |
| "The prediction model has not been trained yet" | The administrator needs to run `python -m loanlens.model`. |
| "Sorry, something went wrong..." | Check the inputs and try again; contact the administrator if it repeats. |

---

## Part 2: For bank managers (Bulk Check)

### Getting in

1. Open **Bulk Check** and switch on **Bank manager mode** in the sidebar.
2. Enter the **manager password**. It is set by the administrator through the `LOANLENS_MANAGER_PASSWORD` environment variable or `.streamlit/secrets.toml`. On a local demo where neither is set, the password is `loanlens-demo` and the sidebar says so.

This is a **prototype gate, not real authentication**.

### Preparing the CSV

Click **Download CSV template** for a 3-row example. One applicant per row, **up to 50,000 rows** per file.

| Column | Required | Description | Allowed values |
|---|---|---|---|
| `applicant_id` | optional | Your own reference, copied to the results. Not stored by LoanLens. | any text |
| `cibil_score` | yes | CIBIL credit score | whole number, 300 to 900 |
| `income_annum` | yes | Annual income in rupees | more than 0 |
| `loan_amount` | yes | Requested loan in rupees | more than 0 |
| `loan_term` | yes | Loan term in years | whole number, 1 to 40 |
| `residential_assets_value` | yes | Residential property value, Rs | 0 or more |
| `commercial_assets_value` | yes | Commercial property value, Rs | 0 or more |
| `luxury_assets_value` | yes | Luxury assets value, Rs | 0 or more |
| `bank_asset_value` | yes | Bank balances and deposits, Rs | 0 or more |

Template rows:

```csv
applicant_id,cibil_score,income_annum,loan_amount,loan_term,residential_assets_value,commercial_assets_value,luxury_assets_value,bank_asset_value
APP-0001,780,6000000,15000000,10,12000000,4000000,10000000,5000000
APP-0002,640,2500000,7500000,15,3000000,1000000,3000000,1000000
```

Tips:

- Headers are matched ignoring case and spaces, and common names are recognised (for example *Income* or *annual_income* for `income_annum`, *Tenure* for `loan_term`, *Credit score* for `cibil_score`, *Loan ID* for `applicant_id`). The page lists which headers it recognised and which it ignored.
- If a required column is missing, the page names exactly which ones.
- Amounts may be written as `1250000`, `12,50,000` or `Rs 12,50,000`. Comma, semicolon, tab and pipe separators all work.
- A **blank asset cell is an error**, not 0: write 0 if the applicant has none.
- Do not include names, phone numbers or other personal details; they are not needed.

### Running a check

1. Upload the file. Tick *Also list positive factors* only if you need them (slower).
2. **Skipped rows** (amber panel): rows with problems are not scored. Open the list to see each one with its spreadsheet row number (header = row 1) and every problem in it. Fix them and upload again if needed. The rest of the file is still scored.
3. **Summary cards:** total scored (blue), approved (green), rejected (red), borderline (amber), skipped rows (grey) and approval rate, plus the top rejection reasons.
4. **Results table:** filter by status, borderline, or search for an ID or a reason. Status cells are coloured and always show the word "Approved" or "Rejected". (For more than 5,000 visible rows, colours are switched off for speed; the words stay.)
5. **Download all results (CSV):** plain data, one row per scored applicant.

### Result columns

| Column | Meaning |
|---|---|
| `row` | Spreadsheet row number in your file |
| `applicant_id` | Your reference (blank if you did not provide one) |
| `status` | Approved or Rejected |
| `probability` | Model score, 0 to 1 (stored value) |
| `likelihood` | Display version with its band, e.g. ">99% - Very likely" |
| `borderline` | True if manual review is recommended (see Part 1, "How the borderline flag works") |
| `reasons` | Rejection reasons, separated by "; " |
| `what_would_change` | Smallest CIBIL increase or loan reduction that would likely change a rejection |
| `warnings` | Out-of-range inputs and advisory-rule notices |
| `reason_codes` | Machine-readable reason codes (used for the summary) |

### What is stored

Only an **anonymised summary** of each batch (counts, approval rate, likelihood bands, top rejection reason codes, model version) is saved to `data/loanlens.sqlite`, and appears on the **Analytics** page. No names, IDs or applicant values are stored unless an administrator sets `storage.store_applicant_ids: true` in `config/policy.yaml`.

### Speed and limits

About 0.7 seconds per 1,000 rows; a 50,000-row file takes roughly 16-32 seconds. Files above 50,000 rows are refused with a message asking you to split them.

### Remember

Results support pre-screening only. All policy thresholds are placeholders, the EMI check uses an assumed 10% interest rate, and the model learned from synthetic data. A borderline or unexpected result should always get a human review.
