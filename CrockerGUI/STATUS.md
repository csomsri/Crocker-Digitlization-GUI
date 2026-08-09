# Project Status
This is a document addressing the current status, plans, and direction of the project.

## Current Status
**8/8/2026**:

    Simplified the AI Control section to expose only the operational PID Control
    page. Removed the Exploration and PID gain-tuning experiment pages from the
    GUI while the tuning workflow is reconsidered.

**7/14/2026**:

    Right now the backend of the GUI is able to read data from a simulator and be able change the magnetic field from the simulator via hardcoded control commands in a test case.

    Therefore we need to make it so that:
    - Read real time data (first the simulator then ZMQ)
    - Be able to control the simulations / ZMQ via the UI Field Control Page

    Once we have finished we are eitehr able to:
    - Continue with other pages of the GUI
    - Start on the Automation process and only care able the field control

**7/15/2026**:

    Field Control Page done (sort of) it is good enough were we can move on but the interaction for the selection of channels are not correct and of course, no sequencer.

    What we have is a visualization using a speedometer to indicate the value of the the channel, but also a secondary plot over time to show the error of the control system over time.

    Next we need to implement other back end properties such as the PID but once the lab is not shut down we are able to test the digital GUI control via ZMQ as we are running on simulation!

**7/19/2026**:

    Added a PID controller to the C++ control system with configurable output limits,
    input validation, first-sample derivative protection, integral anti-windup, reset
    support, and unit tests. The PID test builds and passes successfully.

    Added Exploration and Optimization pages to the AI Control section of the GUI.
    These are placeholder workspaces for now, and upcoming development will focus on
    the Optimization page.

    Next steps:
    - Integrate the PID controller with the simulator, ControlService, and Optimization GUI.
    - Implement and test Bayesian Optimization (BO) safely against the simulator.
    - Define the beam-quality objective, controllable parameters, and safety constraints.

    REMINDER: Add continuous data logging to a database as a background process soon.
    The logger should record telemetry, commands, PID state, optimization trials, alarms,
    and timestamps without blocking the GUI or control loop.

## Plans for what's next
We have proved that a PID works within the digital architecture in the hardware therefore we are able to do some automated task.

### PID and PID Tuning
Need to implement the PID control system and let the constants of the PID be tuned by Bayesian Optimization.
- I have found several papers regarding on what to do: What interests me is a Safety Constraint Bayesian Optimization with Gaussian Processes.
- High dimensionality Bayesian Optimization with Audoencoders


Later we would want to do data exploration via Genetic Algoritm (GA)

## Direction ahead
After we have finish the control system GUI, we need to find ways to add the GPU, some ways to optimize the system system is:
- Data Processesing via GPU
- OpenGL Cuda Interopping (Shared Memory Buffers) for smoother rendering


Then for visualization we want something impressive
- Volumetric Visualization
- Explainable AI via Viz
- LLM Sense making for weird data

I really want to make some cool volumetric visualization if possible
