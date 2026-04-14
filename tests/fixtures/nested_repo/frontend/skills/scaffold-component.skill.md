---
agentmd: "1.0"
type: skill
id: scaffold-react-component
version: "1.2"
description: "Scaffold a new React component with tests and Storybook story"
trigger: "when asked to create a new React component"
inputs:
  - name: component_name
    type: string
    required: true
  - name: variant
    type: enum
    values: [functional, compound, page]
    default: functional
outputs:
  - "src/components/{component_name}/{component_name}.tsx"
  - "src/components/{component_name}/{component_name}.test.tsx"
  - "src/components/{component_name}/{component_name}.stories.tsx"
  - "src/components/{component_name}/index.ts"
tags:
  - frontend
  - react
  - scaffold
---

## Steps

1. Create the component file using the functional template.
2. Generate the test file with React Testing Library.
3. Create a Storybook story for the component.
4. Export from the index file.
