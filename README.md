# BouStrategy

** IN PROGRESS **

## About

BouStrategy attempts to create an investment agent that revolves around a human-written investment framework. Agents operate under a system that researches, reasons, trades, logs its reasoning, monitors thesis validity. A public dashboard will display performance of the trading run operated by BouStrategy agent.  

The core challenge is building an investment harness that is able to deeply consider and execute upon investment frameworks and constraints. Agents will:

- follow a defined mandate

- differentiate noise from real opportunities,

- avoid spewing consensus takes leading to undifferentiated investment decisions,

- monitor active theses without forcing trades

- act boldly when evidence warrants

- log every serious decision

- obey deterministic risk and execution constraints

- and explain every actionable and non actionable insight

To see more details and my comprehensive vision + structure, see `boustrategy_spec.md` and docs/ and plans/

For a public-facing account of the architecture, labeling work, failures, and path to paper and
live trading, see [DEVELOPMENT.md](DEVELOPMENT.md).

## Local operator interface

On Windows, double-click `start-boustrategy.cmd` to open the supervised paper workflow in your
browser. The interface guides digesting, session preparation, and reasoning while leaving the X
and agent steps under human control. See [the operator guide](docs/reasoning/OPERATOR_GUIDE.md) for
the short walkthrough.
