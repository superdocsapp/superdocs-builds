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
        Fill in the placeholders with these exact values, preserve all formatting:
        Client: ${client.name}
        Engagement: ${engagement.title}
        Start Date: ${formatDate(engagement.start_date)}
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
