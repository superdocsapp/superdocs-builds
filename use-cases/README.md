# Maple House — Welcome Book & Policy Set

Built on SuperDocs for the Round 2 hiring task.

## Overview

A multilingual property welcome-book workflow for **Maple House**, managed by **Maple Stay Co.**

The build includes an English guest welcome book, a Hindi version, and a grounded official policy set. The workflow was tested for factual consistency, cross-language propagation, and safe handling of unsupported property information.

## Property

- **Property:** Maple House
- **Operator:** Maple Stay Co.
- **Address:** 24 Garden Lane, Bengaluru, Karnataka, India
- **Check-in:** 3:00pm
- **Check-out:** 11:00am
- **Maximum guests:** 4

## Included artifacts

- `maple-house-welcome-book-english.docx` — English guest welcome book
- `maple-house-welcome-book-hindi.docx` — Hindi guest welcome book
- `maple-house-official-policy-set.docx` — Official policy set covering rental terms, damage policy, and cancellation terms

## What was tested

### Cross-document propagation

The property lock code was changed from:

`4826 → 7391`

The updated value was verified in both the English and Hindi welcome books.

Other important factual values were kept consistent across language versions, including Wi-Fi details, times, phone numbers, names, and appliance references.

### No-op behavior

An instruction containing content that was already correct was tested:

> Welcome to Maple House

SuperDocs correctly recognized that no change was required and did not introduce an unnecessary edit.

### Local recommendations

The welcome book was configured with:

- Garden Cafe
- Central Market
- City Park

### Policy grounding

The official policy set contains the supported rental terms:

- Check-in: 3:00pm
- Check-out: 11:00am
- Maximum guests: 4
- Minimum stay: 2 nights
- Quiet hours: 10:00pm–7:00am
- No parties or events

Where the property record did not provide information, the policy set explicitly says so rather than inventing terms:

- No damage policy provided in the property record.
- Cancellation terms were not provided in the property record.

No unsupported fees, penalties, or refund percentages were added.

## Diagram / asset limitation

The original template referenced:

- `smart-tv-controls`
- `washing-machine-controls`

These were text references rather than available image assets. No asset/image library or actual diagram files were available in the document, so no diagrams were invented.

## Languages

The welcome book was produced in:

- English
- Hindi

Important factual values were preserved during translation rather than translated or altered.

## Built for

SuperDocs Round 2 hiring task — assigned property welcome-book build.

Built by **Ejaz Belgaum**.