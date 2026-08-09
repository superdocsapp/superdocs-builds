"""Amendment and Q&A Delta Applier.

Diffs a GovCon amendment/Q&A document against the original solicitation,
maps affected proposal sections (including second-order effects), stages
traceable edits against the in-flight proposal through the SuperDocs API,
and produces an amendment-response log for the compliance file.
"""

__version__ = "0.1.0"
