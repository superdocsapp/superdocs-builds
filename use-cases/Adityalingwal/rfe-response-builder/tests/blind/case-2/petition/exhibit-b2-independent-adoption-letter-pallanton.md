*Fictional sample document created for software testing. No real person, company, agency, or case is depicted.*

**EXHIBIT B-2**

---

**PALLANTON MUNICIPAL POWER AUTHORITY**
Office of the Chief Grid Architect
915 Dunmore Avenue, Pallanton, MI 49331
Tel (231) 555-0177

---

October 14, 2025

U.S. Citizenship and Immigration Services
Texas Service Center
6820 Merrivale Loop
Mesquite, TX 75149-8802

**RE: Independent implementation of Drift-Indexed Impedance Spectroscopy — Dr. Anselm Ferreira-Duarte**

Dear Officer:

I am the Chief Grid Architect of the Pallanton Municipal Power Authority, a public utility serving
approximately 141,000 metered customers in western Michigan. I hold a doctorate in power systems
engineering from Calderfield State University (2006) and have worked in utility engineering for
nineteen years.

I have been asked to describe our use of a method developed by Dr. Anselm Ferreira-Duarte. I have
never met Dr. Ferreira-Duarte and have had no correspondence with him. Before being contacted by
counsel in this matter I did not know where he worked. I state for the record that the Pallanton
Municipal Power Authority has no commercial relationship of any kind with Voltaris Grid Dynamics,
Inc.: we have never purchased from them, we have never contracted with them, and we do not hold
and have never held any interest in that company. Our monitoring hardware is supplied by a
different vendor. I receive no payment for this letter and the Authority has received nothing of
value in connection with it.

## What we operate

The Authority operates two grid-connected battery installations: the Wrenfield facility, 28 MWh of
lithium-iron-phosphate cells commissioned in 2019, and the Ockley Ridge facility, 11 MWh
commissioned in 2022. Between them they contain a little over 96,000 individual cells.

## Why we changed our monitoring

In February 2022 we had a module fire at Wrenfield. Nobody was hurt and the loss was confined to
one string, but the post-incident review was uncomfortable reading. Our surface thermal monitoring
had raised its first alarm four minutes before the smoke detector. Our engineers concluded from
the recovered cell that the originating fault had been developing for the better part of two
hours. Four minutes of warning is of no use to anyone.

Our reliability group was directed to find a detection method that would give us hours rather than
minutes and that would run on the battery management hardware already installed at both sites,
since re-instrumenting was not affordable. In the course of that search they brought me the 2020
paper by Ferreira-Duarte and Almqvist-Rowe describing Drift-Indexed Impedance Spectroscopy, and
the 2022 follow-on paper describing the HeliosGuard detection model. We chose that method because
it was the only candidate that met the second constraint. The published description was complete
enough for our own engineers to implement it; we did not license anything and we did not engage
the authors.

## What we implemented and what it has done

We implemented drift-indexed monitoring at Wrenfield in November 2022 and at Ockley Ridge in March
2023. Implementation took two of our engineers approximately five months, most of which was spent
on data plumbing rather than on the method itself.

Since commissioning, the system has flagged eleven cells at Wrenfield and three at Ockley Ridge.
In each case we isolated the string and removed the module. Destructive examination by our
laboratory confirmed the presence of lithium plating or separator damage consistent with an
incipient internal short in twelve of the fourteen cells. The remaining two were inconclusive. We
have had no false positive that reached the point of module removal.

The median warning time, measured from the first drift alarm to the point at which our surface
thermal monitoring would have alarmed on the same cell, was 5.4 hours across the fourteen events.
That is the difference between a scheduled removal on a weekday morning and an emergency.

We have had no thermal incident at either facility since implementation.

## My view of the contribution

I am an operator, not a researcher, and I will not offer an opinion on where this work sits in the
academic literature. What I can say is that a method published by this individual is now the
primary safety detection layer on 39 MWh of public infrastructure serving a city, that it was
implemented by strangers from the published description alone, and that it has caught fourteen
cells that our previous method would have caught hours later or not at all. I am aware of at least
two other municipal utilities in this region that have done the same thing, having discussed it
with their engineers at the Midwest Public Power Reliability Forum in 2024.

Sincerely,

**Rasheed Olubanjo-Vance**
Dr. Rasheed Olubanjo-Vance, PhD, PE
Chief Grid Architect
Pallanton Municipal Power Authority
