async (page) => {
  const last = page.locator("article").last();
  await last.scrollIntoViewIfNeeded();
  return last.boundingBox();
}
