// maps DB rate_cards row (snake case to camel case) splitInvoiceByRate expects camel case

export function mapRateRow(row) {
    return {
        hourlyRate: Number(row.hourly_rate),
        currency: row.currency,
        effectiveFrom: row.effective_from,
    };
}

//  maps a DB timesheet_entries row to what splitInvoiceByRate expects
export function mapTimesheetRow(row) {
    return {
        date: row.entry_date,
        hours: Number(row.hours),
        description: row.description,
    };
}
