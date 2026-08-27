export interface StudyPreset {
  id: string;
  name: string;
  badge: string;
  subject: string;
  topic: string;
  targetExam: string;
  notes: string;
}

export const PRESETS: StudyPreset[] = [
  {
    id: 'physics-maxwell',
    name: "⚡ Maxwell's Equations (Physics)",
    badge: 'Physics / STEM',
    subject: 'Classical Electrodynamics & Optics',
    topic: "Maxwell's Equations & Electromagnetic Wave Propagation",
    targetExam: 'University STEM / Graduate Physics',
    notes: `Electrodynamics Lecture Notes - Prof. Thorne
Topic: Unification of Electricity and Magnetism & Displacement Current

1. Gauss's Law (Electrostatics):
Flux through closed surface equals enclosed charge over eps0:
del . E = rho / eps0 (Differential form)
Integral form: closed_int E . dA = Q_enc / eps0

2. Gauss's Law for Magnetism:
No isolated magnetic monopoles in nature.
del . B = 0
Total magnetic flux through any Gaussian surface is identically zero.

3. Faraday's Law of Induction:
Changing magnetic flux creates electric field.
del x E = - dB / dt
Negative sign is Lenz's law (opposes the change in flux).

4. Ampère's Law with Maxwell's Correction:
Original Ampere law: del x B = mu0 * J
Problem: Taking divergence: del . (del x B) = 0, but continuity equation says del . J = - d(rho)/dt != 0 for charging capacitor!
Maxwell added displacement current: J_D = eps0 * dE/dt
Corrected Ampere-Maxwell Law:
del x B = mu0 * J + mu0 * eps0 * dE / dt

5. Wave Equation in Vacuum (rho = 0, J = 0):
Take curl of Faraday: del x (del x E) = - d/dt (del x B)
Vector identity: del(del . E) - del^2 E = - del^2 E (since del . E = 0)
Substitute del x B = mu0 eps0 dE/dt:
- del^2 E = - mu0 eps0 d^2 E / dt^2
=> del^2 E - (1/c^2) d^2 E / dt^2 = 0
Speed of light in vacuum c = 1 / sqrt(mu0 * eps0) ~ 3.00 x 10^8 m/s!`,
  },
  {
    id: 'finance-black-scholes',
    name: '📈 Black-Scholes Formula (Quant)',
    badge: 'Quantitative Finance',
    subject: 'Financial Engineering & Derivatives Pricing',
    topic: 'Black-Scholes-Merton Option Pricing Model',
    targetExam: 'CFA / Master in Quantitative Finance',
    notes: `Financial Calculus - Lecture 7
Continuous-time arbitrage-free option pricing under geometric Brownian motion:
dS_t = mu * S_t * dt + sigma * S_t * dW_t

1. Black-Scholes PDE:
dV/dt + 0.5 * sigma^2 * S^2 * d^2V/dS^2 + r * S * dV/dS - r * V = 0
Key Insight: Dynamic Delta-Hedging eliminates stochastic Brownian term dW_t.

2. European Call Option Formula:
C(S, t) = S0 * N(d1) - K * exp(-r * (T-t)) * N(d2)

3. European Put Option Formula:
P(S, t) = K * exp(-r * (T-t)) * N(-d2) - S0 * N(-d1)

Where:
d1 = [ ln(S0 / K) + (r + 0.5 * sigma^2) * (T-t) ] / [ sigma * sqrt(T-t) ]
d2 = d1 - sigma * sqrt(T-t)
N(x) is standard normal cumulative distribution function (CDF).

4. Put-Call Parity:
C + K * exp(-r * (T-t)) = P + S0`,
  },
  {
    id: 'cs-master-theorem',
    name: '💻 Master Theorem (Algorithms)',
    badge: 'Computer Science',
    subject: 'Design & Analysis of Algorithms',
    topic: 'Divide-and-Conquer Recurrences & Master Theorem',
    targetExam: 'GATE CS / University Algorithms',
    notes: `Algorithm Complexity Notes:
Recurrence relation for divide and conquer:
T(n) = a * T(n/b) + f(n)
where a >= 1 (number of subproblems), b > 1 (subproblem size divisor), and f(n) = Theta(n^d) is combining cost.

Critical parameter: c_crit = log_b(a)

Case 1 (Work dominated by leaves):
If f(n) = O(n^c) where c < log_b(a), then T(n) = Theta(n^(log_b(a)))

Case 2 (Work evenly distributed across all tree levels):
If f(n) = Theta(n^(log_b(a)) * log^k(n)), then T(n) = Theta(n^(log_b(a)) * log^(k+1)(n))
Example: MergeSort has a=2, b=2, f(n)=O(n). log_2(2) = 1 => T(n) = Theta(n log n).

Case 3 (Work dominated by root):
If f(n) = Omega(n^c) where c > log_b(a) and regularity condition a*f(n/b) <= k*f(n) for k < 1,
then T(n) = Theta(f(n)).`,
  },
  {
    id: 'anthro-evolution',
    name: '🧬 Human Evolution (Anthroholic)',
    badge: 'UPSC / Anthropology',
    subject: 'Physical Anthropology & Human Genetics',
    topic: 'Phylogenetic Radiation of Hominins & Cranial Encephalization',
    targetExam: 'UPSC Civil Services Mains (Optional Paper 1)',
    notes: `Anthropology Optional Revision Notes - Anthroholic Series
Topic: Hominization Process and Evolutionary Trends

1. Key Bipedal Adaptations:
- Foramen Magnum positioned anteriorly (centralized under cranium).
- Sigmoid (S-shaped) vertebral column with lumbar lordosis.
- Pelvis broadened, shortened (ilium flared) with abductor mechanism.
- Bicondylar (valgus) knee angle (~9-10 degrees).

2. Cranial Capacity Expansion (Encephalization Quotient):
- Australopithecus afarensis: ~400 - 500 cc
- Homo habilis (Handy Man): ~650 - 750 cc (Oldowan pebble tools)
- Homo erectus (Java/Peking Man): ~900 - 1100 cc (Acheulean handaxe)
- Homo neanderthalensis: ~1400 - 1600 cc (Mousterian culture)
- Homo sapiens: ~1350 - 1450 cc (High vaulted skull, prominent chin)

3. Quantitative Allometric Cranial Index:
Allometric scaling equation: Brain_Weight = alpha * (Body_Weight)^beta where beta ~ 0.66.
Encephalization Quotient EQ = Observed Brain / Expected Brain for body mass.`,
  },
];
