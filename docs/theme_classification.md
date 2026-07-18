# Theme classification

> **Status: inactive reference.** Do not use this document as context, evidence,
> instruction, or a source of priors in research, thesis generation, Investment
> Decision Records, policy evaluation, sizing, or order decisions. It is retained
> only as a possible foundation for future work and has no decision-making
> authority unless the maintainer explicitly adopts it later.

This document defines the theme IDs used to classify signals, decisions, and
portfolio concentration. A theme ID describes the dominant source of risk or
return in an idea. It is not an investment endorsement.

Every BUY or ADD must stand on the company-specific reasoning in its Investment
Decision Record. A theme may also contain a short maintainer thesis capsule when
there is a broad view worth preserving. A dedicated theme memo is optional and
should be created only when several decisions depend on the same causal chain,
the portfolio has meaningful exposure to the theme, or shared monitoring and
invalidation rules would add value.

## Classification rules

- Choose the theme that best describes what must go right for the investment to
  work as `primary_theme_id`.
- Record other material exposures as secondary theme IDs when useful, but do not
  use overlap to count the same position several times for concentration.
- Classify a company by the thesis being expressed, not by every market in which
  it participates.
- Definitions and examples below clarify classification only. They do not
  authorize an order or imply that an example is attractive at its current
  price.
- `emergent_theme` routes an idea into research. It cannot directly support an
  order until the idea has been assigned a vetted theme ID.
- A missing thesis capsule means that no broad maintainer view has been adopted.
  It does not prevent a well-supported company-specific decision.

## `ai_semiconductors`

**Definition:** Compute, memory, and semiconductor manufacturing exposure whose
economics are materially driven by AI workloads.

**Includes:** AI accelerators, CPUs used in AI systems, high-bandwidth memory,
semiconductor manufacturing equipment, foundries, and advanced packaging when
the core bet is semiconductor demand or production economics.

**Excludes:** Servers, datacenter operators, power supply, networking systems,
and AI applications when those are the dominant exposure.

**Common overlaps:** `ai_infrastructure`, `ai_bottlenecks`,
`networking_interconnect`, `data_centers`

_No maintainer thesis currently adopted._

## `ai_infrastructure`

**Definition:** The broad compute and supporting systems required to train,
deploy, and operate AI models.

**Includes:** AI servers, compute platforms, cloud capacity, storage, networking,
and integrated infrastructure suppliers when the thesis depends on the overall
AI buildout rather than one narrower constraint.

**Excludes:** A semiconductor, networking, datacenter, or power thesis when that
narrower layer is the dominant reason for the investment; application software
whose economics primarily depend on selling an AI product.

**Common overlaps:** `ai_semiconductors`, `ai_bottlenecks`, `data_centers`,
`power_grid_electrification`, `cloud_hyperscalers`,
`networking_interconnect`

### Current thesis capsule

**Working view:** Mature AI may have effects that the general public still
underestimates, but that belief does not by itself make current AI-infrastructure
securities attractive. Markets may already expect exceptional capital spending,
so even rapid growth could disappoint if it decelerates.

**Confidence:** Low. This is a research prior, not an actionable thesis.

**Central uncertainty:** Inference may become a much larger long-run workload if
frontier pre-training stops scaling as aggressively and models become cheaper to
run. It is unclear whether growth in usage will outrun efficiency gains or
whether the resulting economics will accrue to centralized infrastructure,
personal devices, or software.

**Material risks:** Datacenter and AI regulation, particularly as the 2028
election cycle approaches; infrastructure overcapacity; valuations that require
continued acceleration; and a shift of inference toward personal devices.

**Current portfolio implication:** No theme-level preference for exposure.
Individual investments must stand on company-specific evidence. The inability to
name confident mechanism-level invalidation criteria is itself a reason not to
act on this broad prior.

**Related observation:** Apple may be positioned to distribute personal
intelligence through its devices and ecosystem, but the current view is
defensive: success may protect its relevance rather than create a new earnings
engine. This is not presently an AI-infrastructure investment thesis.

**Last reviewed:** 2026-07-18

## `ai_bottlenecks`

**Definition:** A scarce input or constrained production step that limits AI
deployment and may give its suppliers unusual pricing power.

**Includes:** Advanced packaging, specialized memory, manufacturing capacity,
critical components, cooling, equipment, or other constraints when scarcity is
the central thesis.

**Excludes:** General participation in AI spending without evidence of a binding
constraint or durable supplier advantage.

**Common overlaps:** `ai_semiconductors`, `ai_infrastructure`, `data_centers`,
`power_grid_electrification`, `networking_interconnect`

_No maintainer thesis currently adopted._

## `data_centers`

**Definition:** Physical facilities and facility-level systems used to house and
operate compute.

**Includes:** Datacenter owners and operators, colocation, construction and
facility equipment, cooling, backup power, and related real estate when facility
demand or economics drive the thesis.

**Excludes:** Utilities and grid equipment, cloud platforms, chips, or networking
when their economics—not the facility—are the dominant exposure.

**Common overlaps:** `ai_infrastructure`, `ai_bottlenecks`,
`power_grid_electrification`, `cloud_hyperscalers`,
`networking_interconnect`

_No maintainer thesis currently adopted._

## `power_grid_electrification`

**Definition:** Electricity generation, transmission, distribution, and
electrical equipment benefiting from greater power demand or electrification.

**Includes:** Utilities, generators, grid equipment, transformers, switchgear,
transmission, energy storage, and electrical infrastructure when power demand or
grid investment is the core bet.

**Excludes:** Datacenter equipment or AI infrastructure whose value is not
primarily determined by power markets or grid spending.

**Common overlaps:** `data_centers`, `ai_infrastructure`, `ai_bottlenecks`,
`macro_liquidity`

_No maintainer thesis currently adopted._

## `financial_technology`

**Definition:** Technology-led changes to payments, banking, brokerage, lending,
insurance, market infrastructure, or other financial services.

**Includes:** Digital payments, financial platforms, technology-enabled brokers
and lenders, financial infrastructure, and software when changes to financial
distribution or unit economics drive the thesis.

**Excludes:** Conventional financial institutions with no material technology
thesis and general software sold to non-financial markets.

**Common overlaps:** `ai_software`, `cybersecurity`, `broad_risk_on_tech`,
`macro_liquidity`

_No maintainer thesis currently adopted._

## `cloud_hyperscalers`

**Definition:** Large cloud platforms whose scale, capital spending, and bundled
services shape the economics of compute and AI distribution.

**Includes:** Public-cloud capacity, platform services, and vertically integrated
AI distribution when hyperscaler economics are the dominant investment driver.

**Excludes:** Cloud-hosted software vendors, datacenter landlords, or component
suppliers whose returns do not primarily depend on operating a hyperscale cloud
platform.

**Common overlaps:** `ai_infrastructure`, `data_centers`, `ai_software`,
`networking_interconnect`, `broad_risk_on_tech`

_No maintainer thesis currently adopted._

## `networking_interconnect`

**Definition:** Technologies that move data within and between compute systems,
datacenters, and networks.

**Includes:** Switching, routing, optical connectivity, interconnect, networking
silicon, and related systems when bandwidth, latency, or network architecture is
the core thesis.

**Excludes:** General semiconductor or infrastructure exposure where networking
is incidental rather than the reason the investment works.

**Common overlaps:** `ai_semiconductors`, `ai_infrastructure`,
`ai_bottlenecks`, `data_centers`, `cloud_hyperscalers`

_No maintainer thesis currently adopted._

## `robotics_automation`

**Definition:** Hardware and software that automate physical work, industrial
processes, or machine operation.

**Includes:** Industrial robots, autonomous machines, factory automation,
machine vision, motion control, and enabling systems when physical automation is
the main source of expected value.

**Excludes:** Purely digital workflow software, general-purpose AI models, and
industrial companies using automation without selling or controlling the
relevant technology.

**Common overlaps:** `ai_software`, `ai_semiconductors`, `ai_infrastructure`

_No maintainer thesis currently adopted._

## `cybersecurity`

**Definition:** Products and services that protect identities, devices,
applications, networks, cloud systems, and data.

**Includes:** Security platforms, identity and access management, endpoint,
network, cloud, application, and data security when security demand and vendor
economics drive the thesis.

**Excludes:** General networking or software exposure without security as the
principal customer need.

**Common overlaps:** `ai_software`, `cloud_hyperscalers`,
`networking_interconnect`, `broad_risk_on_tech`

_No maintainer thesis currently adopted._

## `ai_software`

**Definition:** Software whose product value or economics materially depend on
AI capabilities.

**Includes:** AI-native applications, model platforms, developer tools, agents,
and incumbent software with a specific, economically material AI product thesis.

**Excludes:** Vague claims that ordinary software is "AI-enabled," and hardware
or cloud capacity whose returns come primarily from supplying compute.

**Common overlaps:** `cloud_hyperscalers`, `financial_technology`,
`robotics_automation`, `cybersecurity`, `broad_risk_on_tech`

_No maintainer thesis currently adopted._

## `broad_risk_on_tech`

**Definition:** Technology exposure driven primarily by broad risk appetite,
growth expectations, momentum, or valuation expansion rather than a narrower
operating thesis.

**Includes:** Broad technology indexes, baskets, and individual securities when
the actual bet is a favorable environment for long-duration or high-beta
technology assets.

**Excludes:** Ideas supported by a more specific company or industry mechanism
that should be classified under that narrower theme.

**Common overlaps:** Most technology themes, especially `macro_liquidity`

_No maintainer thesis currently adopted._

## `macro_liquidity`

**Definition:** Exposure whose outcome depends primarily on interest rates,
financial conditions, money and credit availability, fiscal conditions, or
market-wide liquidity.

**Includes:** Cross-asset or equity decisions where discount rates, liquidity,
or macro policy are the dominant causal driver.

**Excludes:** Company-specific decisions for which macro conditions are relevant
context but not the main reason the investment should work.

**Common overlaps:** `broad_risk_on_tech`, `financial_technology`, and any
rate-sensitive theme

_No maintainer thesis currently adopted._

## `emergent_theme`

**Definition:** A temporary research label for a potentially important pattern
that does not yet fit the vetted taxonomy.

**Includes:** Newly observed technologies, business models, constraints, or
market narratives that warrant investigation before classification.

**Excludes:** A convenient miscellaneous category for ideas that could be
classified with existing IDs.

**Common overlaps:** Unknown until the research initiative defines the theme.

`emergent_theme` may open a research initiative but cannot directly support an
order. Before an actionable decision, either assign the idea to an existing
theme or add a new vetted ID to this taxonomy.

_No maintainer thesis currently adopted._
