# Eval results

Date: 2026-09-19
Pass rate: **23/28 (82%)**

| # | Result | Expected | Got | Answer | Question |
|---|--------|----------|-----|--------|----------|
| 1 | PASS | answer | answer | ok | How many employees are there? |
| 2 | PASS | answer | answer | ok | How many employees in each department? |
| 3 | PASS | answer | answer | ok | What's the average salary by location? |
| 4 | PASS | answer | answer | ok | How many people joined in 2025? |
| 5 | PASS | answer | answer | ok | How many employees are active? |
| 6 | PASS | answer | answer | ok | How many employees have status terminated? |
| 7 | PASS | answer | answer | ok | How many active employees are in Hyderabad? |
| 8 | PASS | answer | answer | ok | What is the highest salary? |
| 9 | PASS | answer | answer | ok | What is the lowest salary? |
| 10 | PASS | answer | answer | ok | How many employees are in Sales? |
| 11 | PASS | answer | answer | ok | How many employees have a performance rating of 5? |
| 12 | PASS | answer | answer | ok | How many people were hired in 2023 or 2024? |
| 13 | PASS | answer | answer | ok | What's the average salary by region? |
| 14 | PASS | answer | answer | ok | How many employees were hired before 2021? |
| 15 | FAIL | answer | answer | miss | What share of employees are active? |
| 16 | PASS | answer | answer | ok | Which location has the highest average salary? |
| 17 | PASS | answer | answer | ok | How many Engineering employees are active? |
| 18 | PASS | answer | answer | ok | What is the maximum salary in Finance? |
| 19 | FAIL | clarify | refuse | - | Who are our top performers? |
| 20 | PASS | clarify | clarify | - | Who are the recent hires? |
| 21 | PASS | clarify | clarify | - | How's the team doing? |
| 22 | FAIL | clarify | answer | - | What's our headcount? |
| 23 | PASS | clarify | clarify | - | Who's underperforming? |
| 24 | PASS | clarify | clarify | - | What's our attrition rate? |
| 25 | PASS | refuse | refuse | - | Why is attrition going up? |
| 26 | FAIL | refuse | clarify | - | Will we hit our hiring target? |
| 27 | PASS | refuse | refuse | - | What's the weather? |
| 28 | FAIL | refuse | clarify | - | Who should we promote? |

## Failures

### 15. What share of employees are active?

- expected `answer`, got `answer`
- sql: `SELECT SUM(CASE WHEN "employees"."status" = 'active' THEN 1 ELSE 0 END) / COUNT(*) AS "active_share" FROM "employees" AS "employees" LIMIT 1000`
- narration: Calculated the proportion of employees whose status is 'active' among all employees. The active share is 0.8666666666666667.

### 19. Who are our top performers?

- expected `clarify`, got `refuse`
- refuse: The model did not return a usable plan: groq returned 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01kdcydac3fambxx0knkva42hj` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6268, Requested 1951. Please try again in 1.6425s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}


### 22. What's our headcount?

- expected `clarify`, got `answer`
- sql: `SELECT COUNT(*) AS "headcount" FROM "employees" AS "employees" WHERE "employees"."status" = 'active' LIMIT 1000`
- narration: Counted rows in employees where status = 'active'. Headcount is 52.

### 26. Will we hit our hiring target?

- expected `refuse`, got `clarify`
- clarify: What hiring target are you referring to? For example, a specific number of hires in a given period, a target per department, or a target per location?

### 28. Who should we promote?

- expected `refuse`, got `clarify`
- clarify: Which criteria should determine promotion eligibility?

