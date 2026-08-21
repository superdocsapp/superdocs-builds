import { describe, it, expect } from "vitest";
import { splitInvoiceByRate } from "./invoice.js";

describe("splitInvoiceByRate", () => {
    it("splits an invoice correctly when the rate changes mid-engagement", () => {
        const rateHistory = [
            { effectiveFrom: "2026-01-01", hourlyRate: 1000, currency: "INR" },
            { effectiveFrom: "2026-01-16", hourlyRate: 1200, currency: "INR" },
        ];

        const timesheet = [
            { date: "2026-01-05", hours: 20, description: "Week 1" },
            { date: "2026-01-12", hours: 20, description: "Week 2" },
            { date: "2026-01-20", hours: 10, description: "Week 3, new rate" },
            { date: "2026-01-27", hours: 10, description: "Week 4, new rate" },
        ];

        const result = splitInvoiceByRate(timesheet, rateHistory);

        expect(result.totalHours).toBe(60);

        expect(result.lineItems).toHaveLength(2);

        const oldRateLine = result.lineItems.find((l) => l.hourlyRate === 1000);
        const newRateLine = result.lineItems.find((l) => l.hourlyRate === 1200);

        expect(oldRateLine.hours).toBe(40);
        expect(oldRateLine.amount).toBe(40000);

        expect(newRateLine.hours).toBe(20);
        expect(newRateLine.amount).toBe(24000);

        expect(result.totalAmount).toBe(64000);
        expect(result.totalAmount).toBe(
            oldRateLine.amount + newRateLine.amount,
        );
    });

    it("reconciles total amount to sum of line item amounts, always", () => {
        const rateHistory = [
            { effectiveFrom: "2026-01-01", hourlyRate: 500, currency: "INR" },
        ];
        const timesheet = [
            { date: "2026-01-03", hours: 8, description: "Day 1" },
            { date: "2026-01-04", hours: 6, description: "Day 2" },
        ];

        const result = splitInvoiceByRate(timesheet, rateHistory);
        const sumOfLines = result.lineItems.reduce(
            (acc, l) => acc + l.amount,
            0,
        );

        expect(result.totalAmount).toBe(sumOfLines);
        expect(result.lineItems).toHaveLength(1);
    });
});
