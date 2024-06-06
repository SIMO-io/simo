This component represents a physical button that can be used with other components in the system as a control input.

Usually, it is better to use the input ports of a colonel board directly as input controls. However, if you want to control something that is connected to a different kernel or control more than one component with a single button, then this component provides a way to do it.

Create a button first, then use it as a control input on the component that you want to control.

Bonus feature! A single button can be assigned to multiple components as a control input.

Use GND as a reference. If the SIMO.io Input Port module is in use, set PULL to UP.

---

{% if component.bonded_gear %}
### Bonded gear:

{% for comp in component.bonded_gear %}
- {{ comp }}
{% endfor %}
{% endif %}