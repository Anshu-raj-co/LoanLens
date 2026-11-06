# LoanLens User Guide

LoanLens is a **prototype** that gives a quick, explained pre-eligibility check for a loan. It estimates whether an application looks like those that were **approved** in a public, synthetic dataset. It is **not a lending decision**, it does **not** predict whether a loan would be repaid (default), and every policy limit it uses is an **illustrative placeholder** until replaced by a lender's real credit policy.

Start the app with `streamlit run app/Home.py` (setup: see README.md) and open the address it prints, usually http://localhost:8501. Use the sidebar to move between pages.

---

## Part 0: Accounts and signing in

Home, Sign in and About are open to everyone. Every other page needs you to be signed in.

| You are | You can use |
|---|---|
| An **applicant** | Check My Eligibility and Account |
| A **bank manager** | Check My Eligibility, Bulk Check, Analytics, Users and Account |

### Create an account (applicants)

1. Open **Sign in** and choose the **Create account** tab.
2. Enter your email address and a password twice, then press **Create account**. You are signed in straight away.

Passwords need 10 to 128 characters, must not be a common password and must not be your email address. A passphrase of a few unrelated words works well. Bank manager accounts cannot be created here; an administrator or another manager creates them.

### Sign in and sign out

- On the **Sign in** tab enter your email and password. If anything is wrong, the message is always "Incorrect email or password", so it never reveals whether an email has an account.
- After **5 wrong passwords in a row** the account is locked for **15 minutes**. While it is locked, even the right password is refused.
- The sidebar shows the email and role you are signed in with, and a **Sign out** button.
- A session lasts 60 minutes. **Refreshing or closing the browser tab also signs you out**; just sign in again.

### Forgotten password

There is no email reset. Ask a bank manager to set a **temporary password** for you (Users page). When you sign in with it you must choose a new password on the **Account** page before you can use the other pages.

### Account page

- **Change password:** enter your current password and the new one twice.
- **Delete account:** tick the confirmation box, enter your password and press **Delete my account**. Your email address and password are removed and you are signed out. This cannot be undone.

### What is stored about you

Your email address, a one-way scrambled form of your password (never the password itself), your role, the time the account was created and your last sign-in, and a counter of failed sign-ins. A log of sign-ins and account changes is kept without your email address or password. Email addresses are not checked to be real. What you type into the eligibility form is not stored.

---

## Part 1: For applicants (Check My Eligibility)

Sign in first (Part 0). Bank managers can use this page too.

### Choose the loan type

At the top of the form, pick the **Loan type**: Personal loan (the default), Home loan or Vehicle loan. The loan type changes the policy limits the check uses (for example the allowed loan term, how many times your income you may borrow, and the interest rate assumed for the EMI). It does **not** change the prediction model: every loan type is scored by the same model, which learned from one synthetic dataset that has no loan-type information. The note under the selector shows the limits for the type you picked.

| Loan type | Loan term | Loan up to (x annual income) | Loan up to (x total assets) | Assumed interest rate |
|---|---|---|---|---|
| Personal (default) | 2 to 20 years | 4.0x | 1.5x | 10% |
| Home | 5 to 30 years | 6.0x | 2.0x | 8.5% |
| Vehicle | 1 to 7 years | 1.5x | 1.0x | 11% |

All of these are illustrative placeholders. The model only saw loan terms of 2 to 20 years and loans of 1.5 to 4 times income, so values outside that range (for example a 25-year home loan) get a warning that the result is less reliable.

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

Under the result, a small line names the loan type, its policy version and the model version that produced it.

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

The word "Borderline" in the likelihood band (35-65%) is only a description of the score; the amber pill is what means *manual review recommended*. All of these numbers are placeholders in the policy profiles in `config/policies/`.

### Common messages

| Message | What to do |
|---|---|
| "Please correct the following and try again" | A field is missing or impossible (for example income of 0). Fix the listed fields. |
| "The prediction model has not been trained yet" | The administrator needs to run `python -m loanlens.model`. |
| "Sorry, something went wrong..." | Check the inputs and try again; contact the administrator if it repeats. |
| "Incorrect email or password" | Check both and try again. After 5 wrong tries the account is locked for 15 minutes; a bank manager can unlock it by setting a temporary password. |
| "Please sign in to use this page" | Open **Sign in** in the sidebar. |
| "Your session has ended. Please sign in again." | The 60 minutes are up, or the account was changed by a manager. Sign in again. |
| "This is available to bank managers only." | The page is for bank managers; applicants cannot open it. |
| "You must choose a new password before you can continue." | Open **Account** and change the temporary password. |

---

## Part 2: For bank managers (Bulk Check)

### Getting in

1. Sign in with your **bank manager account** on the **Sign in** page.
2. Open **Bulk Check** in the sidebar.

Manager accounts are created by an administrator (`python -m loanlens.auth create-manager --email <email>`, which asks for the password at a hidden prompt) or by another manager on the **Users** page. A new manager must change the temporary password at first sign-in.

### Preparing the CSV

Click **Download CSV template** for a 3-row example. One applicant per row, **up to 50,000 rows** per file.

| Column | Required | Description | Allowed values |
|---|---|---|---|
| `applicant_id` | optional | Your own reference, copied to the results. Not stored by LoanLens. | any text |
| `product` | optional | Loan type for this row. Blank means personal. Any other value is reported as a row problem and the row is skipped. Also recognised as *Loan type*. | `personal`, `home` or `vehicle` (any case) |
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
- Each row is checked under its own loan type's limits (see Part 1, "Choose the loan type"). Without a `product` column every row is a personal loan.
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
| `product` | The loan type the row was checked under |
| `status` | Approved or Rejected |
| `probability` | Model score, 0 to 1 (stored value) |
| `likelihood` | Display version with its band, e.g. ">99% - Very likely" |
| `borderline` | True if manual review is recommended (see Part 1, "How the borderline flag works") |
| `reasons` | Rejection reasons, separated by "; " |
| `what_would_change` | Smallest CIBIL increase or loan reduction that would likely change a rejection |
| `warnings` | Out-of-range inputs and advisory-rule notices |
| `reason_codes` | Machine-readable reason codes (used for the summary) |

### What is stored

Only an **anonymised summary** of each batch (counts, approval rate, likelihood bands, top rejection reason codes, model version) is saved, and appears on the **Analytics** page. By default it goes to the local file `data/loanlens.sqlite`; an administrator can point LoanLens at another database (for example PostgreSQL) with the `DATABASE_URL` setting. No names, IDs or applicant values are stored unless an administrator sets `storage.store_applicant_ids: true` in `config/policies/personal.yaml`. If the database cannot be reached, the results still appear and a short note says the summary was not saved.

### Speed and limits

About 0.7 seconds per 1,000 rows; a 50,000-row file takes roughly 16-32 seconds. Files above 50,000 rows are refused with a message asking you to split them.

### The Users page

Managers see every account: email, role, status (Active, Locked, Deactivated, or must change password), when it was created and the last sign-in. From here you can:

- **Create a manager:** enter the email and a temporary password twice. Give the password to the person directly; they must change it at first sign-in.
- **Deactivate or reactivate an account:** a deactivated account cannot sign in, and an open session ends at its next page load. You cannot change your own status.
- **Set a temporary password:** use this when someone has forgotten their password. It also unlocks a locked account, and they must choose a new password at their next sign-in.

### Remember

Results support pre-screening only. All policy thresholds are placeholders, the EMI check uses an assumed 10% interest rate, and the model learned from synthetic data. A borderline or unexpected result should always get a human review.
