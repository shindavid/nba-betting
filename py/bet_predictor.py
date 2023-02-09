"""
Chris Andersen and David Shin made a bet prior to the 2022-2023 NBA season. Each NBA team was claimed by exactly one
of the two bettors. At the end of the 2022-2023 playoffs, each team scores 1 point per playoff game won. The bettor
with the most points wins the bet. The play-in game does not count.

This script predicts the outcome of the bet.

At a high-level, the prediction is currently made in the following manner:

* 538's RAPTOR model is used to estimate each individual player's contribution to their team per-100 possessions, as
  well as to their team's average possessions per game.

* Season minutes data is used to model each player's expected minutes per game.

* The above is used to model each team's expected points for/against per game.

* Pythagorean expectation is used to model each team's expected win percentage based on the expected points for/against
  per game.

* Expected win percentage is plugged into the Log5 formula to model any given game outcome. The model may adjust the
  raw win percentage based on home court advantage, rest, etc.

* A Monte Carlo simulation is performed to model the remainder of the regular season and playoffs. The simulation
  results are used to predict the final outcome of the bet.
"""

from teams import *


DAVID_TEAMS = [ MIL, PHX, DAL, MIA, PHI, CLE, CHI, LAC, POR, NYK, CHA, IND, SAC, OKC, HOU ]
CHRIS_TEAMS = [ GSW, MEM, BOS, BKN, DEN, UTA, MIN, NOP, ATL, TOR, LAL, SAS, WAS, ORL, DET ]
