This component represents a physical button that can be used with other components in the system as a control input.
Usually, it is better to use the input ports of a colonel board directly as input controls. 
However, if you want to control something that is connected to a different colonel or control more than one component with a single button, then this component provides a way to do it.

- Create a button first, then use it as a control input on components that you want to control.
- Use GND as a reference. 
- PULL -> UP if used with SIMO.io input port module.

{% if component.controller.bonded_gear %}
---
### Bonded gear:

{% for comp in component.controller.bonded_gear %}
- [{{comp.id}}] {{ comp }}
{% endfor %}
{% endif %}