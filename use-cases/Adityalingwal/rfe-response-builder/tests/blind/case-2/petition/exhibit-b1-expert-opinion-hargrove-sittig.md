*Fictional sample document created for software testing. No real person, company, agency, or case is depicted.*

**EXHIBIT B-1**

---

**WINTERBOURNE POLYTECHNIC UNIVERSITY**
Department of Electrical Energy Systems
1120 Calder Hall, Sheldrake, OR 97465
Tel (541) 555-0122

---

October 9, 2025

U.S. Citizenship and Immigration Services
Texas Service Center
6820 Merrivale Loop
Mesquite, TX 75149-8802

**RE: Dr. Anselm Ferreira-Duarte — opinion on the significance of his scientific contributions**

Dear Officer:

I write at the request of counsel for Voltaris Grid Dynamics, Inc. to give my independent
assessment of the scientific contributions of Dr. Anselm Ferreira-Duarte. I receive no payment for
this letter.

## My qualifications and my relationship to Dr. Ferreira-Duarte

I am the Kettleborough Chair of Electrical Energy Systems at Winterbourne Polytechnic University,
where I have taught since 2004 and have headed the department since 2018. I hold a doctorate in
electrochemical engineering from Ravensmoor University (1999). I have published 141 peer-reviewed
articles on battery degradation and failure prediction, and I served on the North American Storage
Safety Council's Technical Committee 44 from 2019 to 2025. Since 2021 I have been Editor-in-Chief
of the *Journal of Grid-Scale Storage Systems*.

I state plainly what my connection to Dr. Ferreira-Duarte is and is not. I have never employed
him, supervised him, taught him, co-authored any paper with him, or held any financial interest in
any company that employs him. I first became aware of his work in 2019 when a manuscript of his
was submitted to a conference I chaired. We have met in person three times, at conferences. In my
editorial capacity I have assigned him manuscripts to review, which I describe at the end of this
letter.

## The problem his work addresses

Thermal runaway in a large lithium-iron-phosphate installation is not a single event but a
cascade. One cell develops an internal short circuit; it heats; it heats its neighbours; the
neighbours fail in turn. By the time a thermal sensor on the outside of a module registers an
anomaly, the originating cell has typically been in distress for somewhere between forty minutes
and three hours, and in most array geometries the cascade can no longer be arrested by isolating
the affected string. The field understood this well before 2020. What it did not have was a
practical way to see the originating fault while it was still a single-cell problem, using
instrumentation that could be afforded at the scale of tens of thousands of cells.

## What Dr. Ferreira-Duarte contributed

Dr. Ferreira-Duarte's insight, published in 2020 and refined in 2022, was that the onset of an
internal short leaves a signature in the *drift* of the cell's impedance response over hours,
rather than in any single impedance measurement. Absolute impedance varies so widely between
nominally identical cells, and with state of charge and temperature, that per-cell thresholds had
been abandoned as unworkable. By indexing each cell against its own trailing history rather than
against a population value, he removed the source of variance that had defeated earlier attempts.
This is the technique now known as Drift-Indexed Impedance Spectroscopy.

Two things distinguish this from an incremental improvement.

First, it is a change of frame, not a change of parameter. Prior work sought better thresholds.
DIIS discards the threshold entirely. Reviewers of the 2020 manuscript, including one who
recommended rejection, recorded in their reports that the approach was not a variation on existing
methods.

Second, it works on the hardware that operators already own. DIIS requires no additional sensing
hardware beyond the impedance measurement capability present in most commercial battery management
systems manufactured after 2017. That is why adoption has been fast. A method that requires
re-instrumenting an installed base of forty million cells does not get adopted, however elegant.

## How the field has taken it up

I can point to four concrete forms of uptake.

**Incorporation into a standard.** North American Storage Safety Council Standard NASSC 4412-2024,
*Early Detection of Cell-Level Thermal Anomalies in Stationary Storage*, published in June 2024,
specifies drift-indexed impedance monitoring as an accepted detection method at Clause 7.3.2, and
cites his 2020 paper in the informative references at Annex B. I sat on Technical Committee 44
while that clause was drafted. The clause exists because of his work; there was no other candidate
method that met the committee's cost and retrofit constraints.

**Independent deployment.** Operators unconnected to his employer have implemented the method.
Exhibit B-2 is a letter from the Chief Grid Architect of the Pallanton Municipal Power Authority,
which is a customer of neither Voltaris nor the Kessendra Institute, describing their own
implementation and its results.

**Citation and extension.** The 2020 paper had been cited 412 times as of September 2025. I have
read a substantial share of those citing papers. The great majority are not courtesy citations.
Groups at four institutions I would name as leading in this area have built directly on the
method: two have extended it to nickel-manganese-cobalt chemistries, one has adapted it to
second-life automotive packs, and one has published a hardware implementation that runs the
indexing on the module controller rather than centrally.

**Replication.** In 2023 an independent group published a replication study on a 4.2 MWh array
that was not built with his involvement and reported detection at a median of 6.1 hours before
surface temperature rise. Replication by strangers is the strongest evidence a method is real.

## My assessment

I am asked whether these contributions are of major significance to the field. In my judgement
they are, and I would say so of very few people. The test I apply is whether the field would be
doing something materially different today had the person not done the work. For DIIS the answer
is yes: the detection clause of NASSC 4412-2024 would not exist in its present form, and the
operators now running drift-indexed monitoring would be running surface thermal monitoring, which
we all knew to be too late. Dr. Ferreira-Duarte is, in my opinion, among the small number of
people at the very top of the field of battery storage safety engineering.

## Peer review for this journal

Because it is relevant to a separate question, I confirm the following in my editorial capacity.
Dr. Ferreira-Duarte has served on the reviewer panel of the *Journal of Grid-Scale Storage
Systems* since March 2022. Our records show that he has completed fourteen manuscript reviews for
the journal between March 2022 and August 2025. Reviewers for this journal are invited by the
editorial board and are not self-nominated.

I am available should you require anything further.

Sincerely,

**Elenora Hargrove-Sittig**
Prof. Elenora Hargrove-Sittig, PhD
Kettleborough Chair of Electrical Energy Systems
Winterbourne Polytechnic University
Editor-in-Chief, *Journal of Grid-Scale Storage Systems*

*Enclosure: curriculum vitae (14 pages)*
