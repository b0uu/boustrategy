# BouStrategy

<img width="1501" height="759" alt="image" src="https://github.com/user-attachments/assets/6872014a-2871-4b28-9d8d-74aeeba3b9b5" />


## About

BouStrategy is my attempt to create an autonomous investment agent that revolves around an investment framework that aligns with my personal style of investing. Agents operate under a system that researches, reasons, trades, logs its reasoning, and monitors thesis validity. 

A public dashboard at [boustrategy.com](https://boustrategy.com) displays the performance of the trading run operated by my own instance of this agent, as well as detailed reasoning & decision traces for each decision. For my first run, I started by funding the Agentic Robinhood account with $100, and after weeks of trial and evaluations, I will further fund.  

The main differentiating factor that I wanted for this agent was some factor of sentiment and knowledge from trusted, yet informal sources, as this has always been a crucial point of investment for me in my past. To implement this, I decided to have an input via a curated set of Twitter (X) accounts, which complements the research pipeline.

## How it works

The agentic process starts with a series of structured steps. It first reviews all of the information that it has, including recent tweets from monitored X accounts, ____. It then conducts live research for potential investments with the added context in mind, and reasons within the investment framework, which serves as a core investment strategy. Lastly, based on its evaluation, it makes a decision.

Before a live order can be executed, the decision must pass through our deterministic policy checks and schema validation, which provides us with constraints that limit risk, exposure, and control for source reliability. This is in order to limit the negative impact that could result from a poor agent judgement call.

The system records all decisions, including a decision not to trade at all. A pass, watchlist, or decision to continue holding can be as important as a buy or sell because it shows how the agent is responding to the available evidence.

## How informal sources are used

If we rely solely on formal company releases or mainstream financial news, there would be lots of crucial information that would be fully missed, and as a result, it would make it much easier to misprice something. 

Informal yet trusted sources & opinions are useful to me because they can provide additional context, sentiment, and observations aren't immediately obvious to the public, which is crucial to actually finding an edge, and having some type of edge is the only thing that matters in investing. 

As I continue to develop this, I hope to add even more points of informal sourcing such as relevant tech newsletters, private discord servers, and more. 
