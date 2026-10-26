// Builds the skeleton HTML and instruction text for an engagement letter.
// Takes real client and engagement data, no API calls here.
export function buildEngagementLetter({ client, engagement, rateHistory }) {
    const currentRate = rateHistory[rateHistory.length - 1];

    const skeletonHtml = `
        <h1>Engagement Letter</h1>
        <p>Client: TBD</p>
        <p>Engagement: TBD</p>
        <p>Start Date: TBD</p>
        <p>Rate: TBD</p>
        <p>This letter confirms the engagement described above, including the agreed hourly rate and start date</p>
    `.trim();

    const instruction = `
        Fill in the placeholders with these exact values, preserve all formatting. Propose every edit together as a single batch, do not stage them across multiple review rounds.
        Client: ${client.name}
        Engagement: ${engagement.title}
        Start Date: ${engagement.start_date}
        Rate: ${currentRate.hourlyRate} ${currentRate.currency} per hour
    `.trim();

    return {
        filename: `engagement-letter-${engagement.id}.html`,
        skeletonHtml,
        instruction,
    };
}

// formats a JS Date or date string as YYYY-MM-DD for clean display in documents.
function formatDate(date) {
    if (date instanceof Date) {
        return date.toISOString().slice(0, 10);
    }
    return date;
}

// builds the skeleton HTML and instruction text for a timesheet and lists every logged entry so nothing gets summarized or dropped
export function buildTimesheet({ client, engagement, timesheet }) {
    const placeholderRows = timesheet
        .map(() => "<tr><td>TBD</td><td>TBD</td><td>TBD</td></tr>")
        .join("\n");

    const skeletonHtml = `
        <h1>Timesheet</h1>
        <p>Client: TBD</p>
        <p>Engagement: TBD</p>
        <table>
        <tr><th>Date</th><th>Hours</th><th>Description</th></tr>
        ${placeholderRows}
        </table>
        <p>Total Hours: TBD</p>
    `.trim();

    const totalHours = timesheet.reduce((sum, entry) => sum + entry.hours, 0);

    const entriesText = timesheet
        .map(
            (entry, index) =>
                `Row ${index + 1}: ${entry.date} | ${entry.hours} hours | ${entry.description}`,
        )
        .join("\n");

    const instruction = `
        Fill in the placeholders, preserve all formatting. Propose every edit together as a single batch, do not stage them across multiple review rounds. Make one separate edit per placeholder, do not merge multiple placeholders into a single edit, and do not add any content beyond what is described below.
        Client: ${client.name}
        Engagement: ${engagement.title}

        There are ${timesheet.length} placeholder table rows, already present, one per entry. Fill each row with its matching data below, in order, do not add or remove rows:
        ${entriesText}

        Total Hours: ${totalHours}
    `.trim();

    return {
        filename: `timesheet-${engagement.id}.html`,
        skeletonHtml,
        instruction,
    };
}

// builds the skeleton HTML and instruction text for an invoice. one line item per rate period, so a mid-engagement rate change is visibly
// split and auditable, not silently averaged or collapsed into one number
export function buildInvoice({ client, engagement, invoice }) {
    // Build one placeholder row per line item, so every edit is a simple
    // text swap, not a structural table insert the AI has to invent.
    const placeholderRows = invoice.lineItems
        .map(() => "<tr><td>TBD</td><td>TBD</td><td>TBD</td><td>TBD</td></tr>")
        .join("\n");

    const skeletonHtml = `
        <h1>Invoice</h1>
        <p>Client: TBD</p>
        <p>Engagement: TBD</p>
        <table>
        <tr><th>Period Start</th><th>Hours</th><th>Rate</th><th>Amount</th></tr>
        ${placeholderRows}
        </table>
        <p>Total Hours: TBD</p>
        <p>Total Amount: TBD</p>
    `.trim();

    const lineItemsText = invoice.lineItems
        .map(
            (item, index) =>
                `Row ${index + 1}: ${item.effectiveFrom} | ${item.hours} hours | ${item.hourlyRate} ${item.currency}/hr | ${item.amount} ${item.currency}`,
        )
        .join("\n");

    const instruction = `
        Fill in the placeholders, preserve all formatting. Propose every edit together as a single batch, do not stage them across multiple review rounds. Make one separate edit per placeholder, do not merge multiple placeholders into a single edit, and do not add any content beyond what is described below.
        Client: ${client.name}
        Engagement: ${engagement.title}

        There are ${invoice.lineItems.length} placeholder table rows, already present, one per rate period. Fill each cell in each row with its matching data below, in order, do not add or remove rows:
        ${lineItemsText}

        Total Hours: ${invoice.totalHours}
        Total Amount: ${invoice.totalAmount} ${invoice.currency}
    `.trim();

    return {
        filename: `invoice-${engagement.id}.html`,
        skeletonHtml,
        instruction,
    };
}

// Builds the skeleton HTML and instruction text for a payment reminder. outstanding amount = the full invoice total.
export function buildPaymentReminder({ client, engagement, invoice }) {
    const skeletonHtml = `
        <h1>Payment Reminder</h1>
        <p>Client: TBD</p>
        <p>Engagement: TBD</p>
        <p>Outstanding Amount: TBD</p>
        <p>This is a friendly reminder that payment for the above engagement is due.</p>
    `.trim();

    const instruction = `
        Fill in the placeholders with these exact values, preserve all formatting. Propose every edit together as a single batch, do not stage them across multiple review rounds.
        Client: ${client.name}
        Engagement: ${engagement.title}
        Outstanding Amount: ${invoice.totalAmount} ${invoice.currency}
    `.trim();

    return {
        filename: `payment-reminder-${engagement.id}.html`,
        skeletonHtml,
        instruction,
    };
}
