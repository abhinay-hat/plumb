# Eval results

Date: 2026-09-20
Pass rate: **27/30 (90%)**

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
| 15 | PASS | answer | answer | ok | What share of employees are active? |
| 16 | PASS | answer | answer | ok | Which location has the highest average salary? |
| 17 | PASS | answer | answer | ok | How many Engineering employees are active? |
| 18 | PASS | answer | answer | ok | What is the maximum salary in Finance? |
| 19 | PASS | clarify | clarify | - | Who are our top performers? |
| 20 | PASS | clarify | clarify | - | Who are the recent hires? |
| 21 | FAIL | clarify | refuse | - | How's the team doing? |
| 22 | PASS | clarify | clarify | - | What's our headcount? |
| 23 | PASS | clarify | clarify | - | Who's underperforming? |
| 24 | PASS | clarify | clarify | - | What's our attrition rate? |
| 25 | PASS | refuse | refuse | - | Why is attrition going up? |
| 26 | PASS | refuse | refuse | - | Will we hit our hiring target? |
| 27 | PASS | refuse | refuse | - | What's the weather? |
| 28 | FAIL | refuse | clarify | - | Who should we promote? |
| 29 | PASS | dashboard | dashboard | - | Give me an overview of this data |
| 30 | FAIL | dashboard | error | - | What is interesting in this spreadsheet? |

## Failures

### 21. How's the team doing?

- expected `clarify`, got `refuse`
- refuse: The model returned a response plumb could not read. Try again, rephrase the question, or pick a different model.

### 28. Who should we promote?

- expected `refuse`, got `clarify`
- clarify: What criteria should we use to decide who to promote?

### 30. What is interesting in this spreadsheet?

- expected `dashboard`, got `error`

