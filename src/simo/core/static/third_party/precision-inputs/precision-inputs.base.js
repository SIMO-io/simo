window.PrecisionInputs = function (t) {
  function e(i) {
    if (n[i]) return n[i].exports;
    var a = n[i] = {i: i, l: !1, exports: {}};
    return t[i].call(a.exports, a, a.exports, e), a.l = !0, a.exports
  }

  var n = {};
  return e.m = t, e.c = n, e.d = function (t, n, i) {
    e.o(t, n) || Object.defineProperty(t, n, {
      configurable: !1,
      enumerable: !0,
      get: i
    })
  }, e.n = function (t) {
    var n = t && t.__esModule ? function () {
      return t.default
    } : function () {
      return t
    };
    return e.d(n, "a", n), n
  }, e.o = function (t, e) {
    return Object.prototype.hasOwnProperty.call(t, e)
  }, e.p = "", e(e.s = 1)
}([function (t, e, n) {
  "use strict";

  function i(t, e) {
    if (!(t instanceof e)) throw new TypeError("Cannot call a class as a function")
  }

  function a(t, e) {
    for (var n = 0; n < e.length; n++) {
      var i = e[n];
      i.enumerable = i.enumerable || !1, i.configurable = !0, "value" in i && (i.writable = !0), Object.defineProperty(t, i.key, i)
    }
  }

  function s(t, e, n) {
    return e && a(t.prototype, e), n && a(t, n), t
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0, n(2);
  var u = (0, n(3).getTransformProperty)(), o = function () {
    function t(e, n) {
      var a = arguments.length > 2 && void 0 !== arguments[2] ? arguments[2] : {};
      if (i(this, t), !e) throw new Error("KnobInput constructor must receive a valid container element");
      if (!n) throw new Error("KnobInput constructor must receive a valid visual element");
      if (!e.contains(n)) throw new Error("The KnobInput's container element must contain its visual element");
      var s = a.step || "any", o = "number" == typeof a.min ? a.min : 0,
        r = "number" == typeof a.max ? a.max : 1;
      this.initial = "number" == typeof a.initial ? a.initial : .5 * (o + r), this.dragResistance = "number" == typeof a.dragResistance ? a.dragResistance : 100, this.dragResistance *= 3, this.dragResistance /= r - o, this.wheelResistance = "number" == typeof a.wheelResistance ? a.wheelResistance : 100, this.wheelResistance *= 40, this.wheelResistance /= r - o, this.setupVisualContext = "function" == typeof a.visualContext ? a.visualContext : t.setupRotationContext(0, 360), this.updateVisuals = "function" == typeof a.updateVisuals ? a.updateVisuals : t.rotationUpdateFunction;
      var h = document.createElement("input");
      h.type = "range", h.step = s, h.min = o, h.max = r, h.value = this.initial, e.appendChild(h), this._container = e, this._container.classList.add("knob-input__container"), this._input = h, this._input.classList.add("knob-input__input"), this._visualElement = n, this._visualElement.classList.add("knob-input__visual"), this._visualContext = {
        element: this._visualElement,
        transformProperty: u
      }, this.setupVisualContext.apply(this._visualContext), this.updateVisuals = this.updateVisuals.bind(this._visualContext), this._activeDrag = !1, this._handlers = {
        inputChange: this.handleInputChange.bind(this),
        touchStart: this.handleTouchStart.bind(this),
        touchMove: this.handleTouchMove.bind(this),
        touchEnd: this.handleTouchEnd.bind(this),
        touchCancel: this.handleTouchCancel.bind(this),
        mouseDown: this.handleMouseDown.bind(this),
        mouseMove: this.handleMouseMove.bind(this),
        mouseUp: this.handleMouseUp.bind(this),
        mouseWheel: this.handleMouseWheel.bind(this),
        doubleClick: this.handleDoubleClick.bind(this),
        focus: this.handleFocus.bind(this),
        blur: this.handleBlur.bind(this)
      }, this._input.addEventListener("change", this._handlers.inputChange), this._input.addEventListener("touchstart", this._handlers.touchStart), this._input.addEventListener("mousedown", this._handlers.mouseDown), this._input.addEventListener("wheel", this._handlers.mouseWheel), this._input.addEventListener("dblclick", this._handlers.doubleClick), this._input.addEventListener("focus", this._handlers.focus), this._input.addEventListener("blur", this._handlers.blur), this.updateToInputValue()
    }

    return s(t, [{
      key: "handleInputChange", value: function (t) {
        this.updateToInputValue()
      }
    }, {
      key: "handleTouchStart", value: function (t) {
        this.clearDrag(), t.preventDefault();
        var e = t.changedTouches.item(t.changedTouches.length - 1);
        this._activeDrag = e.identifier, this.startDrag(e.clientY), document.body.addEventListener("touchmove", this._handlers.touchMove), document.body.addEventListener("touchend", this._handlers.touchEnd), document.body.addEventListener("touchcancel", this._handlers.touchCancel)
      }
    }, {
      key: "handleTouchMove", value: function (t) {
        var e = this.findActiveTouch(t.changedTouches);
        e ? this.updateDrag(e.clientY) : this.findActiveTouch(t.touches) || this.clearDrag()
      }
    }, {
      key: "handleTouchEnd", value: function (t) {
        var e = this.findActiveTouch(t.changedTouches);
        e && this.finalizeDrag(e.clientY)
      }
    }, {
      key: "handleTouchCancel", value: function (t) {
        this.findActiveTouch(t.changedTouches) && this.clearDrag()
      }
    }, {
      key: "handleMouseDown", value: function (t) {
        this.clearDrag(), t.preventDefault(), this._activeDrag = !0, this.startDrag(t.clientY), document.body.addEventListener("mousemove", this._handlers.mouseMove), document.body.addEventListener("mouseup", this._handlers.mouseUp)
      }
    }, {
      key: "handleMouseMove", value: function (t) {
        1 & t.buttons ? this.updateDrag(t.clientY) : this.finalizeDrag(t.clientY)
      }
    }, {
      key: "handleMouseUp", value: function (t) {
        this.finalizeDrag(t.clientY)
      }
    }, {
      key: "handleMouseWheel", value: function (t) {
        t.preventDefault(), this._input.focus(), this.clearDrag(), this._prevValue = parseFloat(this._input.value), this.updateFromDrag(t.deltaY, this.wheelResistance)
      }
    }, {
      key: "handleDoubleClick", value: function (t) {
        this.clearDrag(), this._input.value = this.initial, this.updateToInputValue()
      }
    }, {
      key: "handleFocus", value: function (t) {
        this._container.classList.add("focus-active")
      }
    }, {
      key: "handleBlur", value: function (t) {
        this._container.classList.remove("focus-active")
      }
    }, {
      key: "startDrag", value: function (t) {
        this._dragStartPosition = t, this._prevValue = parseFloat(this._input.value), this._input.focus(), document.body.classList.add("knob-input__drag-active"), this._container.classList.add("drag-active"), this._input.dispatchEvent(new InputEvent("knobdragstart"))
      }
    }, {
      key: "updateDrag", value: function (t) {
        var e = t - this._dragStartPosition;
        this.updateFromDrag(e, this.dragResistance), this._input.dispatchEvent(new InputEvent("change"))
      }
    }, {
      key: "finalizeDrag", value: function (t) {
        var e = t - this._dragStartPosition;
        this.updateFromDrag(e, this.dragResistance), this.clearDrag(), this._input.dispatchEvent(new InputEvent("change")), this._input.dispatchEvent(new InputEvent("knobdragend"))
      }
    }, {
      key: "clearDrag", value: function () {
        document.body.classList.remove("knob-input__drag-active"), this._container.classList.remove("drag-active"), this._activeDrag = !1, this._input.dispatchEvent(new InputEvent("change")), document.body.removeEventListener("mousemove", this._handlers.mouseMove), document.body.removeEventListener("mouseup", this._handlers.mouseUp), document.body.removeEventListener("touchmove", this._handlers.touchMove), document.body.removeEventListener("touchend", this._handlers.touchEnd), document.body.removeEventListener("touchcancel", this._handlers.touchCancel)
      }
    }, {
      key: "updateToInputValue", value: function () {
        var t = parseFloat(this._input.value);
        this.updateVisuals(this.normalizeValue(t), t)
      }
    }, {
      key: "updateFromDrag", value: function (t, e) {
        var n = this.clampValue(this._prevValue - t / e);
        this._input.value = n, this.updateVisuals(this.normalizeValue(n), n)
      }
    }, {
      key: "clampValue", value: function (t) {
        var e = parseFloat(this._input.min), n = parseFloat(this._input.max);
        return Math.min(Math.max(t, e), n)
      }
    }, {
      key: "normalizeValue", value: function (t) {
        var e = parseFloat(this._input.min);
        return (t - e) / (parseFloat(this._input.max) - e)
      }
    }, {
      key: "findActiveTouch", value: function (t) {
        var e, n;
        for (e = 0, n = t.length; e < n; e++) if (this._activeDrag === t.item(e).identifier) return t.item(e);
        return null
      }
    }, {
      key: "addEventListener", value: function () {
        this._input.addEventListener.apply(this._input, arguments)
      }
    }, {
      key: "removeEventListener", value: function () {
        this._input.removeEventListener.apply(this._input, arguments)
      }
    }, {
      key: "focus", value: function () {
        this._input.focus.apply(this._input, arguments)
      }
    }, {
      key: "blur", value: function () {
        this._input.blur.apply(this._input, arguments)
      }
    }, {
      key: "value", get: function () {
        return parseFloat(this._input.value)
      }, set: function (t) {
        this._input.value = t, this.updateToInputValue(), this._input.dispatchEvent(new Event("change"))
      }
    }], [{
      key: "setupRotationContext", value: function (t, e) {
        return function () {
          this.minRotation = t, this.maxRotation = e
        }
      }
    }, {
      key: "rotationUpdateFunction", value: function (t) {
        this.element.style[this.transformProperty] = "rotate(".concat(this.maxRotation * t - this.minRotation * (t - 1), "deg)")
      }
    }]), t
  }();
  e.default = o
}, function (t, e, n) {
  "use strict";
  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0;
  var i = {
    KnobInput: function (t) {
      return t && t.__esModule ? t : {default: t}
    }(n(0)).default
  };
  e.default = i
}, function (t, e) {
}, function (t, e, n) {
  "use strict";

  function i(t) {
    for (var e = 0; e < t.length; e++) if (void 0 !== document.body.style[t[e]]) return t[e];
    return null
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.getTransformProperty = function () {
    return i(["transform", "msTransform", "webkitTransform", "mozTransform", "oTransform"])
  }, e.debounce = function (t, e, n) {
    var i;
    return function () {
      var a = this, s = arguments, u = n && !i;
      clearTimeout(i), i = setTimeout(function () {
        i = null, n || t.apply(a, s)
      }, e), u && t.apply(a, s)
    }
  }
}]).default;