// All Office.js / Word JavaScript API access is kept in this module so the
// React components never touch Word.run()/context.sync() directly.

function ensureWordAvailable() {
  if (typeof Word === 'undefined') {
    throw new Error('The Word JavaScript API is not available. Open this add-in inside Microsoft Word.')
  }
}

export async function getCurrentDocumentText() {
  ensureWordAvailable()
  return Word.run(async (context) => {
    const body = context.document.body
    body.load('text')
    await context.sync()
    return body.text
  })
}

export async function findPlaceholder(placeholder) {
  ensureWordAvailable()
  return Word.run(async (context) => {
    const results = context.document.body.search(placeholder, { matchCase: false })
    results.load('items')
    await context.sync()
    return results.items.length
  })
}

export async function replacePlaceholder(placeholder, value) {
  ensureWordAvailable()
  return Word.run(async (context) => {
    const results = context.document.body.search(placeholder, { matchCase: false })
    results.load('items')
    await context.sync()

    if (results.items.length === 0) {
      return 0
    }

    results.items.forEach((range) => {
      range.insertText(value === null || value === undefined ? '' : String(value), Word.InsertLocation.replace)
    })

    await context.sync()
    return results.items.length
  })
}

async function deleteFirstMatch(marker) {
  return Word.run(async (context) => {
    const results = context.document.body.search(marker, { matchCase: false })
    results.load('items')
    await context.sync()

    if (results.items.length === 0) {
      return false
    }

    results.items[0].delete()
    await context.sync()
    return true
  })
}

async function deleteAllMatches(marker) {
  return Word.run(async (context) => {
    const results = context.document.body.search(marker, { matchCase: false })
    results.load('items')
    await context.sync()

    results.items.forEach((range) => range.delete())
    await context.sync()
    return results.items.length
  })
}

async function removeConditionalSection(startMarker, endMarker) {
  return Word.run(async (context) => {
    const body = context.document.body
    const startResults = body.search(startMarker, { matchCase: false })
    const endResults = body.search(endMarker, { matchCase: false })
    startResults.load('items')
    endResults.load('items')
    await context.sync()

    if (startResults.items.length === 0 || endResults.items.length === 0) {
      return false
    }

    const sectionRange = startResults.items[0].expandTo(endResults.items[0])
    sectionRange.delete()
    await context.sync()
    return true
  })
}

// Resolves each {{#if field}}...{{/if}} block in the document based on the
// condition results from the backend's condition engine. When a condition
// is include=true, only the marker lines are stripped (the section stays).
// When include=false, the whole block - markers and content - is removed.
// When unresolved (include=null), the block is left untouched.
export async function applyConditions(conditions) {
  ensureWordAvailable()
  const results = []

  for (const condition of conditions) {
    const startMarker = `{{#if ${condition.condition_key}}}`
    const endMarker = '{{/if}}'

    if (condition.include === true) {
      await deleteFirstMatch(startMarker)
      await deleteAllMatches(endMarker)
      results.push({ condition_key: condition.condition_key, applied: 'included' })
    } else if (condition.include === false) {
      const removed = await removeConditionalSection(startMarker, endMarker)
      results.push({ condition_key: condition.condition_key, applied: removed ? 'excluded' : 'not_found' })
    } else {
      results.push({ condition_key: condition.condition_key, applied: 'skipped_unresolved' })
    }
  }

  return results
}

// Applies only the proposed changes the user has reviewed and that are
// ready (i.e. not missing/unresolved). Everything runs as ordinary Word
// edits, so the document's normal undo history still applies.
export async function applyChanges(proposedChanges, conditions = []) {
  ensureWordAvailable()

  const applied = []
  const skipped = []

  for (const change of proposedChanges) {
    if (change.status !== 'ready') {
      skipped.push(change.field)
      continue
    }

    const count = await replacePlaceholder(change.placeholder, change.proposed_value)
    if (count > 0) {
      applied.push({ field: change.field, placeholder: change.placeholder, value: change.proposed_value })
    } else {
      skipped.push(change.field)
    }
  }

  const conditionResults = await applyConditions(conditions)

  return { applied, skipped, conditionResults }
}
