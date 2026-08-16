# Statement of Account and Ageing Pack

## Who it serves

Accounts receivable and credit control teams.

## What was built

A monthly statement-of-account and ageing pack generated from fabricated customer source data.

Each statement includes:

- Customer information
- Statement month
- Opening balance
- Transaction rows
- Closing balance
- Ageing buckets
- Credit-controller narrative with a single recommended action
-  Source-figure verification

## Source data handling

Values appearing in statement tables are carried directly from the authoritative customer source data.

Transaction values are not recomputed from generated prose.

Closing balance and ageing values are taken from the source data rather than derived by reading generated document rows.

## Narrative verification

The credit-controller narrative is generated from selected source facts.
The narrative also contains a single recommended credit-control action based on the account position.
Before the narrative is written to the final document, the verification step:

1. Builds an index of authoritative source figures.
2. Extracts currency figures appearing in the final narrative.
3. Matches each narrative figure against the source data.
4. Rejects any figure that cannot be traced to a source value.
5. Prevents the narrative from being printed when verification fails.

## Detection behavior

The verification was tested with both valid and invalid figures.

A narrative containing:

- `₹28,000`
- `₹5,000`

passes because both values exist in the authoritative source data.

A narrative containing an untraceable value such as:

- `₹25,000`

is rejected rather than guessed or printed.

## Observations

### Where carrying source values held

Transaction rows were successfully carried into the generated document from the source transaction objects.

Opening balance, closing balance, and ageing values were also carried from the source data into the statement.

No totals were recomputed by reading generated document rows or generated prose.

### Where it did not hold

The initial narrative verification treated the `90` in the `90+` ageing bucket label as a financial figure. This was not an authoritative source amount and therefore could not be matched to the source figure index.

The verification logic was adjusted to ignore ageing bucket labels such as `90+` while continuing to inspect currency figures.

After that adjustment, the final narrative verification passed and only traceable currency figures were accepted.

### Tests

The verification test suite covers:

- Carrying every transaction into document rows
- Creating template data from trusted statement values
- Building a statement using source values
- Accepting valid narrative figures
- Rejecting untraceable narrative figures
- Generating a narrative using verified source figures

All 8 verification tests pass.

## Main implementation

The implementation is organized in:

- `src/statement.js`
- `src/narrative.js`
- `src/verify.js`
- `src/templateData.js`
- `src/transactionRows.js`

Tests are in:

- `tests/verification.test.js`

The SuperDoc rendering implementation is in:

- `superdoc-app/src/App.jsx`