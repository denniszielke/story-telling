Create a hand-drawn “whiteboard/sketchnote” visualisation in a casual marker style, similar to a classroom or tutorial whiteboard sketch.
Use a clean white background, thin black ink outlines, and a slightly wobbly hand-drawn look. Apply only limited accent colours (red and blue) for highlights, arrows, numbered steps, section headers, and callout notes.
Title
Place a clear handwritten title at the top:
“{TITLE}”
Overall layout
Use a clean left-to-right visual flow that explains {SCENARIO_DESCRIPTION}.
Organise the diagram into clearly separated boxed sections or layers with handwritten headers.
Use simple hand-drawn icons and short readable labels.
Keep the spacing open and uncluttered so the diagram remains easy to scan and understand.
If relevant, include common visual cues such as:

cloud icon for external network / internet
shield or lock icon for security boundaries
database cylinder for data stores
person icon for human roles
gear / flow / node icons for orchestration or processing
chart / dashboard icons for reporting or insights

Structural organisation
Group the content into {NUMBER_OF_LAYERS} major areas using boxed regions with handwritten headers:

{LAYER_1_NAME}
{LAYER_2_NAME}
{LAYER_3_NAME}
{OPTIONAL_LAYER_4_NAME}

These layers can represent, for example:

users / channels / physical world
business process / application layer
orchestration / agents / services
systems of record / data / analytics
external ecosystem / partners / downstream systems

Components to include
Draw the following components as simple labelled doodles with small icons:

{COMPONENT_1}
{COMPONENT_2}
{COMPONENT_3}
{COMPONENT_4}
{COMPONENT_5}
{COMPONENT_6}
{DATA_STORE_OR_SYSTEM_1}
{DATA_STORE_OR_SYSTEM_2}
{OPTIONAL_COMPONENT_CLUSTER}

If there is a grouped subsystem (for example agents, services, modules, steps, or capabilities), draw it as a larger labelled box containing several smaller boxes inside it.
Flows / interactions to show
Show the key interactions using arrows with short handwritten labels.
Use numbered flows when sequencing matters.
Include the following flows:

{FLOW_1}
{FLOW_2}
{FLOW_3}
{FLOW_4}
{FLOW_5}
{OPTIONAL_FLOW_6}
{OPTIONAL_FLOW_7}

Where appropriate:

show feedback loops
show human-in-the-loop review or approval
show ingestion, transformation, routing, enrichment, storage, analytics, or output
show trust/security/governance boundaries
show upstream and downstream systems
show parallel outputs if needed

Optional callouts
Add 2–4 small handwritten callout bubbles in blue marker near the most important part of the diagram. These should highlight the business or architectural value, for example:

{CALLOUT_1}
{CALLOUT_2}
{CALLOUT_3}
{OPTIONAL_CALLOUT_4}

Style constraints
Keep the visual style:

simple
educational
hand-drawn
easy to understand
suitable for executive or workshop use
visually balanced
readable at presentation size

Do not use

photorealism
glossy UI styling
3D rendering
polished corporate vector style
excessive shading
complex backgrounds
dense text blocks
tiny unreadable labels
overly technical micro-detail
perfect geometric lines

Rendering constraints

white background
black marker outlines
red and blue accents only
minimal light grey scribble shading if needed
high readability
aspect ratio: {ASPECT_RATIO}

Suggested aspect ratios:

16:9 for presentation slides
4:3 for more compact diagrams
1:1 for square social or summary visuals


Optional Negative Prompt
If your generator supports a negative prompt, use:
photorealistic, 3D, glossy, neon, polished UI mockup, heavy gradients, cluttered layout, tiny unreadable text, printed font, vector-perfect lines, dark background, excessive detail, corporate infographic style

Recommended Input Fields
To make the prompt easy to reuse, you can provide the agent with these inputs:

{TITLE} – title shown at the top
{SCENARIO_DESCRIPTION} – one-sentence explanation of what the diagram should depict
{NUMBER_OF_LAYERS} – usually 3 or 4
{LAYER_X_NAME} – section names
{COMPONENT_X} – systems, actors, services, roles, tools, or process steps
{FLOW_X} – short descriptions of the most important interactions
{CALLOUT_X} – benefits, outcomes, risks addressed, or design principles
{ASPECT_RATIO} – 16:9, 4:3, or 1:1