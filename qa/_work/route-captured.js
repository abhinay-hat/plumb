async (page) => {
  const captured = {
    "What's the average salary?": {
      route: "answer",
      sql: 'SELECT AVG("northwind_hr_analytics_compensation"."base_salary_inr") AS "avg_salary" FROM "northwind_hr_analytics_compensation" LIMIT 1000',
      columns: ["avg_salary"],
      rows: [[3050227.168073676]],
      narration:
        "Calculated the average of base_salary_inr from northwind_hr_analytics_compensation. The average salary is 3050227.168073676.",
      chart: null,
      clarify_question: null,
      clarify_options: null,
      refuse_reason: null,
      definitions_applied: {},
      elapsed_ms: 1979,
    },
    "How many employees in each location?": {
      route: "answer",
      sql: 'SELECT location, COUNT(*) AS headcount FROM northwind_hr_analytics_employees GROUP BY location ORDER BY headcount DESC LIMIT 1000',
      columns: ["location", "headcount"],
      rows: [
        ["Hyderabad", 183],
        ["Bengaluru", 122],
        ["Pune", 75],
        ["Gurugram", 57],
        ["Remote - India", 55],
        ["Mumbai", 46],
        ["Chennai", 42],
        ["London", 20],
        ["Singapore", 15],
        ["Dubai", 11],
        ["hyderabad", 4],
        ["bengaluru", 3],
        ["gurugram", 3],
        ["chennai", 2],
        ["pune", 1],
        ["mumbai", 1],
      ],
      narration: "Counted employees in each location. Hyderabad has the highest headcount with 183 employees.",
      chart: null,
      clarify_question: null,
      clarify_options: null,
      refuse_reason: null,
      definitions_applied: {},
      elapsed_ms: 3847,
    },
    "What's the average performance rating?": {
      route: "answer",
      sql: "SELECT AVG(performance_rating) AS avg_rating FROM northwind_hr_analytics_performance_reviews LIMIT 1000",
      columns: ["avg_rating"],
      rows: [[3.1935096153846154]],
      narration:
        "Calculated the average of the performance_rating column. The average performance rating is 3.1935096153846154.",
      chart: null,
      clarify_question: null,
      clarify_options: null,
      refuse_reason: null,
      definitions_applied: {},
      elapsed_ms: 1574,
    },
    "What's our headcount?": {
      route: "clarify",
      sql: null,
      columns: null,
      rows: null,
      narration: null,
      chart: null,
      clarify_question:
        "Do you want the total number of employees in the database or the number of employees currently active (status = 'Active')?",
      clarify_options: ["Total employees", "Active employees"],
      refuse_reason: null,
      definitions_applied: {},
      elapsed_ms: 1000,
    },
  };

  await page.route("**/api/ask", async (route) => {
    const posted = route.request().postDataJSON();
    const q = (posted && posted.question) || "";
    const body = captured[q] || {
      route: "refuse",
      refuse_reason: "no stub",
      definitions_applied: {},
      elapsed_ms: 1,
    };
    await route.fulfill({ json: body });
  });
  return "routed";
}
