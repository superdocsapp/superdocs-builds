// Find the rate that was active on a given entry date (latest rate starting on/before it).
function findApplicableRate(entryDate, sortedRateHistory) {
    let applicable = null;

    for (const rate of sortedRateHistory) {
        if (rate.effectiveFrom <= entryDate) {
            applicable = rate;
        } else {
            break; // rates are sorted, so no need to check further
        }
    }

    // Fails loudly instead of guessing a rate for a date we don't have coverage for.
    if (!applicable) {
        throw new Error(
            `No rate found for entry date ${entryDate}. Earliest rate starts ${sortedRateHistory[0]?.effectiveFrom}.`,
        );
    }

    return applicable;
}

// splits a timesheet into invoice line items, one per rate period.
export function splitInvoiceByRate(timesheet, rateHistory) {
    if (!rateHistory || rateHistory.length === 0) {
        throw new Error("No rate history provided.");
    }

    // Sort oldest to newest so the rate-lookup walk above works correctly.
    const sortedRates = [...rateHistory].sort((a, b) =>
        a.effectiveFrom.localeCompare(b.effectiveFrom),
    );

    // Group timesheet entries by which rate period they fall under.
    const groups = new Map();

    for (const entry of timesheet) {
        const rate = findApplicableRate(entry.date, sortedRates);
        const key = `${rate.hourlyRate}-${rate.currency}-${rate.effectiveFrom}`;

        if (!groups.has(key)) {
            groups.set(key, {
                hourlyRate: rate.hourlyRate,
                currency: rate.currency,
                effectiveFrom: rate.effectiveFrom,
                hours: 0,
                entries: [],
            });
        }

        const group = groups.get(key);
        group.hours += entry.hours;
        group.entries.push(entry);
    }

    // Turn groups into sorted line items, each with its own hours/amount.
    const lineItems = Array.from(groups.values())
        .sort((a, b) => a.effectiveFrom.localeCompare(b.effectiveFrom))
        .map((group) => ({
            hourlyRate: group.hourlyRate,
            currency: group.currency,
            effectiveFrom: group.effectiveFrom,
            hours: group.hours,
            amount: group.hours * group.hourlyRate,
            entries: group.entries,
        }));

    const totalHours = lineItems.reduce((acc, l) => acc + l.hours, 0);

    // Total is always the sum of line items, never computed separately.
    // This is what guarantees totals reconcile to the timesheet.
    const totalAmount = lineItems.reduce((acc, l) => acc + l.amount, 0);

    return {
        lineItems,
        totalHours,
        totalAmount,
        currency: sortedRates[0].currency,
    };
}
