# Chapter 1: Search and Problem Solving

## 1.1 State Spaces and Search Trees

A search problem is defined by an initial state, a set of actions, a transition
model, a goal test, and a path cost. The state space is the set of all states
reachable from the initial state by any sequence of actions. We often picture
the state space as a graph whose nodes are states and whose edges are actions.
A search tree superimposes a tree of paths over this graph, where the root is
the initial state and branches correspond to applying actions. Uninformed
search strategies such as breadth-first search and depth-first search differ in
the order they expand nodes. Breadth-first search expands the shallowest
unexpanded node and is complete and optimal for unit step costs, but its memory
requirement grows exponentially with depth. Depth-first search expands the
deepest node first, uses little memory, but may wander down an infinite branch
and fail to terminate. Iterative deepening combines the modest memory of
depth-first search with the completeness of breadth-first search by repeatedly
running depth-limited searches with an increasing limit.

## 1.2 Informed Search and Heuristics

Informed search strategies use a heuristic function that estimates the cost from
a node to the nearest goal. Greedy best-first search expands the node that
appears closest to the goal according to the heuristic, which is fast but not
optimal. The A star algorithm combines the path cost so far with the heuristic
estimate, expanding the node with the lowest estimated total cost. A star is
optimal whenever the heuristic is admissible, meaning it never overestimates the
true remaining cost, and efficient whenever the heuristic is consistent. The
quality of a heuristic determines how many nodes A star must expand, and a more
informed heuristic dominates a weaker one by expanding fewer nodes.

# Chapter 2: Knowledge Representation

## 2.1 Propositional Logic

Propositional logic represents knowledge using atomic propositions that are
either true or false, combined with logical connectives such as conjunction,
disjunction, negation, implication, and biconditional. A model is an assignment
of truth values to every proposition, and a sentence is satisfiable if some
model makes it true. Entailment holds between a knowledge base and a sentence
when every model of the knowledge base is also a model of the sentence.
Inference algorithms such as resolution and model checking decide entailment.
Resolution is a sound and complete inference rule for propositional logic when
sentences are expressed in conjunctive normal form. The conversion to normal
form may increase the size of the formula, but it enables a uniform refutation
procedure that derives the empty clause from an unsatisfiable set.

## 2.2 First Order Logic

First order logic extends propositional logic with objects, relations, functions,
and quantifiers. The universal quantifier asserts that a property holds for every
object in the domain, while the existential quantifier asserts that it holds for
at least one object. Variables range over objects, and unification finds a
substitution that makes two logical expressions identical. First order inference
uses generalized rules such as universal instantiation and resolution with
unification, giving a far more expressive language than propositional logic at
the cost of a harder inference problem.

# Chapter 3: Logic Programming

## 3.1 Horn Clauses and Resolution

Logic programming expresses knowledge as a set of Horn clauses, where each clause
has at most one positive literal. A definite clause has exactly one positive
literal and zero or more negative literals, written as a head implied by a body
of goals. The Prolog language executes such clauses using backward chaining,
starting from a query and reducing it to subgoals using the clause bodies.
Resolution combined with unification matches a goal against clause heads, binding
variables along the way. Backtracking explores alternative clauses when a chosen
branch fails, undoing variable bindings as it returns to an earlier choice point.

## 3.2 Semantics and the Closed World Assumption

The declarative semantics of a logic program is given by its least Herbrand model,
the smallest set of ground facts consistent with the clauses. The closed world
assumption treats any fact not provable from the program as false, which supports
negation as failure. This assumption is appropriate when the knowledge base is
complete for its domain, but it can produce wrong conclusions when information is
missing. Procedural semantics, by contrast, describes the actual resolution and
backtracking steps the interpreter performs when answering a query.
