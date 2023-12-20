window.PrecisionInputs = function (t) {
  function e(r) {
    if (i[r]) return i[r].exports;
    var n = i[r] = {i: r, l: !1, exports: {}};
    return t[r].call(n.exports, n, n.exports, e), n.l = !0, n.exports
  }

  var i = {};
  return e.m = t, e.c = i, e.d = function (t, i, r) {
    e.o(t, i) || Object.defineProperty(t, i, {
      configurable: !1,
      enumerable: !0,
      get: r
    })
  }, e.n = function (t) {
    var i = t && t.__esModule ? function () {
      return t.default
    } : function () {
      return t
    };
    return e.d(i, "a", i), i
  }, e.o = function (t, e) {
    return Object.prototype.hasOwnProperty.call(t, e)
  }, e.p = "", e(e.s = 6)
}([function (t, e, i) {
  "use strict";

  function r(t, e) {
    if (!(t instanceof e)) throw new TypeError("Cannot call a class as a function")
  }

  function n(t, e) {
    for (var i = 0; i < e.length; i++) {
      var r = e[i];
      r.enumerable = r.enumerable || !1, r.configurable = !0, "value" in r && (r.writable = !0), Object.defineProperty(t, r.key, r)
    }
  }

  function a(t, e, i) {
    return e && n(t.prototype, e), i && n(t, i), t
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0, i(2);
  var o = (0, i(3).getTransformProperty)(), s = function () {
    function t(e, i) {
      var n = arguments.length > 2 && void 0 !== arguments[2] ? arguments[2] : {};
      if (r(this, t), !e) throw new Error("KnobInput constructor must receive a valid container element");
      if (!i) throw new Error("KnobInput constructor must receive a valid visual element");
      if (!e.contains(i)) throw new Error("The KnobInput's container element must contain its visual element");
      var a = n.step || "any", s = "number" == typeof n.min ? n.min : 0,
        l = "number" == typeof n.max ? n.max : 1;
      this.initial = "number" == typeof n.initial ? n.initial : .5 * (s + l), this.dragResistance = "number" == typeof n.dragResistance ? n.dragResistance : 100, this.dragResistance *= 3, this.dragResistance /= l - s, this.wheelResistance = "number" == typeof n.wheelResistance ? n.wheelResistance : 100, this.wheelResistance *= 40, this.wheelResistance /= l - s, this.setupVisualContext = "function" == typeof n.visualContext ? n.visualContext : t.setupRotationContext(0, 360), this.updateVisuals = "function" == typeof n.updateVisuals ? n.updateVisuals : t.rotationUpdateFunction;
      var c = document.createElement("input");
      c.type = "range", c.step = a, c.min = s, c.max = l, c.value = this.initial, e.appendChild(c), this._container = e, this._container.classList.add("knob-input__container"), this._input = c, this._input.classList.add("knob-input__input"), this._visualElement = i, this._visualElement.classList.add("knob-input__visual"), this._visualContext = {
        element: this._visualElement,
        transformProperty: o
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
      }, this._input.addEventListener("change", this._handlers.inputChange),
         this._input.addEventListener("touchstart", this._handlers.touchStart),
         this._input.addEventListener("mousedown", this._handlers.mouseDown),
         this._input.addEventListener("wheel", this._handlers.mouseWheel),
         this._input.addEventListener("dblclick", this._handlers.doubleClick),
         this._input.addEventListener("focus", this._handlers.focus),
         this._input.addEventListener("blur", this._handlers.blur),
         this.updateToInputValue()
    }

    return a(t, [{
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
        var i = this.clampValue(this._prevValue - t / e);
        this._input.value = i, this.updateVisuals(this.normalizeValue(i), i)
      }
    }, {
      key: "clampValue", value: function (t) {
        var e = parseFloat(this._input.min), i = parseFloat(this._input.max);
        return Math.min(Math.max(t, e), i)
      }
    }, {
      key: "normalizeValue", value: function (t) {
        var e = parseFloat(this._input.min);
        return (t - e) / (parseFloat(this._input.max) - e)
      }
    }, {
      key: "findActiveTouch", value: function (t) {
        var e, i;
        for (e = 0, i = t.length; e < i; e++) if (this._activeDrag === t.item(e).identifier) return t.item(e);
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
  e.default = s
}, function (t, e, i) {
  "use strict";
  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0;
  var r = {
    KnobInput: function (t) {
      return t && t.__esModule ? t : {default: t}
    }(i(0)).default
  };
  e.default = r
}, function (t, e) {
}, function (t, e, i) {
  "use strict";

  function r(t) {
    for (var e = 0; e < t.length; e++) if (void 0 !== document.body.style[t[e]]) return t[e];
    return null
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.getTransformProperty = function () {
    return r(["transform", "msTransform", "webkitTransform", "mozTransform", "oTransform"])
  }, e.debounce = function (t, e, i) {
    var r;
    return function () {
      var n = this, a = arguments, o = i && !r;
      clearTimeout(r), r = setTimeout(function () {
        r = null, i || t.apply(n, a)
      }, e), o && t.apply(n, a)
    }
  }
}, function (t, e, i) {
  "use strict";
  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0;
  var r = {val: 9135103, str: "#8b63ff"}, n = {val: 5164287, str: "#4eccff"},
    a = {val: 8645442, str: "#83eb42"}, o = {val: 16108615, str: "#f5cc47"},
    s = {val: 16731744, str: "#ff4e60"}, l = {val: 16754736, str: "#ffa830"},
    c = {
      purple: r,
      blue: n,
      green: a,
      yellow: o,
      red: s,
      orange: l,
      panning: r,
      volume: n,
      modX: a,
      modY: o,
      pitch: s,
      misc: l,
      default: l
    };
  e.default = c
}, function (t, e, i) {
  "use strict";

  function r(t) {
    var e = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : {},
      i = arguments.length > 2 && void 0 !== arguments[2] && arguments[2],
      r = arguments.length > 3 && void 0 !== arguments[3] && arguments[3];
    i && void 0 === e.fill && t.setAttribute("fill", "transparent");
    for (var n in e) e.hasOwnProperty(n) && ("id" === n ? t.id = e[n] : "classes" === n ? Array.isArray(e[n]) ? t.classList.add.apply(t.classList, e[n]) : t.classList.add(e[n]) : t.setAttribute(r ? l(n) : n, e[n]))
  }

  function n(t) {
    var e = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : {},
      i = document.createElementNS(s, t);
    return r(i, e), i
  }

  function a(t) {
    var e = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : .1;
    "number" == typeof e && (t.setAttribute("x", -1 * e), t.setAttribute("y", -1 * e), t.setAttribute("width", 1 + 2 * e), t.setAttribute("height", 1 + 2 * e))
  }

  function o() {
    var t = document.getElementById("precision-inputs-svg-defs");
    if (t) return t;
    var e = document.createElementNS(s, "svg");
    e.style.position = "absolute", e.style.left = 0, e.style.top = 0, e.style.width = 0, e.style.height = 0, e.style.opacity = 0;
    var i = document.createElementNS(s, "defs");
    return i.id = "precision-inputs-svg-defs", e.appendChild(i), document.body.appendChild(e), i
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.createFilterPass = n, e.defineSvgGradient = function (t, e) {
    var i = arguments.length > 2 && void 0 !== arguments[2] ? arguments[2] : {},
      r = arguments.length > 3 && void 0 !== arguments[3] ? arguments[3] : {};
    if (document.getElementById(t)) return "url(#".concat(t, ")");
    if ("linear" !== e && "radial" !== e) throw new Error("Unknown SVG Gradient type: ".concat(e));
    var n = document.createElementNS(s, "linear" === e ? "linearGradient" : "radialGradient");
    n.id = t, n.setAttribute("color-interpolation", "sRGB");
    for (var a in i) i.hasOwnProperty(a) && n.setAttribute(a, i[a]);
    var l;
    for (var c in r) if (r.hasOwnProperty(c)) {
      if (l = document.createElementNS(s, "stop"), isNaN(c)) {
        if ("%" !== c[c.length - 1]) continue;
        l.setAttribute("offset", c)
      } else l.setAttribute("offset", c + "%");
      "string" == typeof r[c] ? l.setAttribute("stop-color", r[c]) : ("string" == typeof r[c].color && l.setAttribute("stop-color", r[c].color), void 0 !== r[c].opacity && l.setAttribute("stop-opacity", r[c].opacity)), n.appendChild(l)
    }
    return o().appendChild(n), "url(#".concat(t, ")")
  }, e.defineBlurFilter = function (t, e) {
    var i = arguments.length > 2 && void 0 !== arguments[2] ? arguments[2] : "none",
      r = arguments.length > 3 && void 0 !== arguments[3] ? arguments[3] : null;
    if (document.getElementById(t)) return "url(#".concat(t, ")");
    var l = document.createElementNS(s, "filter");
    return l.id = t, l.setAttribute("color-interpolation-filters", "sRGB"), a(l, r), l.appendChild(n("feGaussianBlur", {
      in: "SourceGraphic",
      result: "blur",
      stdDeviation: e
    })), "none" !== i && l.appendChild(n("feComposite", {
      in: "blur",
      in2: "SourceGraphic",
      operator: i
    })), o().appendChild(l), "url(#".concat(t, ")")
  }, e.defineDarkenFilter = function (t, e, i) {
    var r = arguments.length > 3 && void 0 !== arguments[3] ? arguments[3] : null;
    if (document.getElementById(t)) return "url(#".concat(t, ")");
    var l = document.createElementNS(s, "filter");
    return l.id = t, l.setAttribute("color-interpolation-filters", "sRGB"), a(l, r), l.appendChild(n("feColorMatrix", {
      in: "SourceGraphic",
      type: "matrix",
      values: "".concat(e, " 0 0 0 ").concat(i, "  0 ").concat(e, " 0 0 ").concat(i, "  0 0 ").concat(e, " 0 ").concat(i, "  0 0 0 1 0")
    })), o().appendChild(l), "url(#".concat(t, ")")
  }, e.defineDropshadowFilter = function (t) {
    var e = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : 0,
      i = arguments.length > 2 && void 0 !== arguments[2] ? arguments[2] : .6,
      r = arguments.length > 3 && void 0 !== arguments[3] ? arguments[3] : 1,
      l = arguments.length > 4 && void 0 !== arguments[4] ? arguments[4] : 3,
      c = arguments.length > 5 && void 0 !== arguments[5] ? arguments[5] : null;
    if (document.getElementById(t)) return "url(#".concat(t, ")");
    var u = document.createElementNS(s, "filter");
    return u.id = t, u.setAttribute("color-interpolation-filters", "sRGB"), a(u, c), u.appendChild(n("feOffset", {
      dx: r,
      dy: l
    })), u.appendChild(n("feColorMatrix", {
      result: "darken",
      type: "matrix",
      values: "0 0 0 0 ".concat((e >> 16 & 255) / 256, "  0 0 0 0 ").concat((e >> 8 & 255) / 256, "  0 0 0 0 ").concat((255 & e) / 256, "  0 0 0 ").concat(i, " 0")
    })), u.appendChild(n("feComposite", {
      in: "SourceGraphic",
      in2: "darken",
      operator: "over"
    })), o().appendChild(u), "url(#".concat(t, ")")
  }, e.defineMask = function (t) {
    var e = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : [];
    if (document.getElementById(t)) return "url(#".concat(t, ")");
    var i = document.createElementNS(s, "mask");
    return i.id = t, e.forEach(function (t) {
      return i.appendChild(t)
    }), o().appendChild(i), "url(#".concat(t, ")")
  }, e.createGroup = function () {
    var t = arguments.length > 0 && void 0 !== arguments[0] ? arguments[0] : {},
      e = document.createElementNS(s, "g");
    return r(e, t, !1, !0), e
  }, e.createRectangle = function (t, e, i, n) {
    var a = arguments.length > 4 && void 0 !== arguments[4] ? arguments[4] : {};
    if (void 0 === t || void 0 === e || void 0 === i || void 0 === n) throw new Error("Missing required parameters for creating SVG rectangle.");
    var o = document.createElementNS(s, "rect");
    return o.setAttribute("x", t), o.setAttribute("y", e), o.setAttribute("width", i), o.setAttribute("height", n), r(o, a, !0, !0), o
  }, e.createCircle = function (t, e, i) {
    var n = arguments.length > 3 && void 0 !== arguments[3] ? arguments[3] : {};
    if (void 0 === t || void 0 === e || void 0 === i) throw new Error("Missing required parameters for creating SVG circle.");
    var a = document.createElementNS(s, "circle");
    return a.setAttribute("cx", t), a.setAttribute("cy", e), a.setAttribute("r", i), r(a, n, !0, !0), a
  }, e.createLine = function (t, e, i, n) {
    var a = arguments.length > 4 && void 0 !== arguments[4] ? arguments[4] : {};
    if (void 0 === t || void 0 === e || void 0 === i || void 0 === n) throw new Error("Missing required parameters for creating SVG line.");
    var o = document.createElementNS(s, "line");
    return o.setAttribute("x1", t), o.setAttribute("y1", e), o.setAttribute("x2", i), o.setAttribute("y2", n), r(o, a, !1, !0), o
  }, e.createPath = function (t) {
    var e = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : {};
    if (void 0 === t) throw new Error("Missing required parameters for creating SVG path.");
    var i = document.createElementNS(s, "path");
    return i.setAttribute("d", t), r(i, e, !0, !0), i
  }, e.svgNS = void 0;
  var s = "http://www.w3.org/2000/svg";
  e.svgNS = s;
  var l = function (t) {
    return t.replace(/([A-Z])/g, function (t) {
      return "-".concat(t[0].toLowerCase())
    })
  }
}, function (t, e, i) {
  "use strict";

  function r(t) {
    return t && t.__esModule ? t : {default: t}
  }

  function n() {
    return (n = Object.assign || function (t) {
      for (var e = 1; e < arguments.length; e++) {
        var i = arguments[e];
        for (var r in i) Object.prototype.hasOwnProperty.call(i, r) && (t[r] = i[r])
      }
      return t
    }).apply(this, arguments)
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0;
  var a = r(i(1)), o = r(i(7)), s = r(i(9)), l = r(i(4)), c = n({
    FLStandardKnob: o.default,
    FLReactiveGripDial: s.default,
    colors: l.default
  }, a.default);
  e.default = c
}, function (t, e, i) {
  "use strict";

  function r(t) {
    return t && t.__esModule ? t : {default: t}
  }

  function n(t) {
    return (n = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (t) {
      return typeof t
    } : function (t) {
      return t && "function" == typeof Symbol && t.constructor === Symbol && t !== Symbol.prototype ? "symbol" : typeof t
    })(t)
  }

  function a(t, e) {
    if (!(t instanceof e)) throw new TypeError("Cannot call a class as a function")
  }

  function o(t, e) {
    for (var i = 0; i < e.length; i++) {
      var r = e[i];
      r.enumerable = r.enumerable || !1, r.configurable = !0, "value" in r && (r.writable = !0), Object.defineProperty(t, r.key, r)
    }
  }

  function s(t, e, i) {
    return e && o(t.prototype, e), i && o(t, i), t
  }

  function l(t, e) {
    if (e && ("object" === n(e) || "function" == typeof e)) return e;
    if (!t) throw new ReferenceError("this hasn't been initialised - super() hasn't been called");
    return t
  }

  function c(t, e) {
    if ("function" != typeof e && null !== e) throw new TypeError("Super expression must either be null or a function");
    t.prototype = Object.create(e && e.prototype, {
      constructor: {
        value: t,
        enumerable: !1,
        writable: !0,
        configurable: !0
      }
    }), e && (Object.setPrototypeOf ? Object.setPrototypeOf(t, e) : t.__proto__ = e)
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0, i(8);
  var u = i(5), d = r(i(4)), h = r(i(0)), f = function (t) {
    function e(t) {
      var i = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : {};
      if (a(this, e), !t) throw new Error("FLStandardKnob constructor must receive a valid container element");
      var r = void 0 === i.indicatorDot || i.indicatorDot,
        n = void 0 !== i.indicatorRingType ? i.indicatorRingType : "positive",
        o = void 0 !== i.color ? i.color : d.default.default.str,
        s = e._constructVisualElement(r, o);
      return i.visualContext = e._getVisualSetupFunction(r), i.updateVisuals = e._getVisualUpdateFunction(r, n), t.classList.add("fl-standard-knob"), t.appendChild(s), l(this, (e.__proto__ || Object.getPrototypeOf(e)).call(this, t, s, i))
    }

    return c(e, h.default), s(e, null, [{
      key: "_constructVisualElement", value: function (t, e) {
        var i = document.createElementNS(u.svgNS, "svg");
        i.classList.add("fl-standard-knob__svg"), i.setAttribute("viewBox", "0 0 40 40"), (0, u.defineBlurFilter)("filter__fl-standard-knob__focus-indicator-glow", 2, "none", .2);
        var r = document.createElementNS(u.svgNS, "circle");
        r.classList.add("fl-standard-knob__focus-indicator"), r.setAttribute("cx", 20), r.setAttribute("cy", 20), r.setAttribute("r", 18), r.setAttribute("fill", e), r.setAttribute("filter", "url(#filter__fl-standard-knob__focus-indicator-glow)");
        var n = document.createElementNS(u.svgNS, "circle");
        n.classList.add("fl-standard-knob__indicator-ring-bg"), n.setAttribute("cx", 20), n.setAttribute("cy", 20), n.setAttribute("r", 18), n.setAttribute("fill", "#353b3f"), n.setAttribute("stroke", "#23292d");
        var a = document.createElementNS(u.svgNS, "path");
        a.classList.add("fl-standard-knob__indicator-ring"), a.setAttribute("d", "M20,20Z"), a.setAttribute("fill", e);
        var o = document.createElementNS(u.svgNS, "g");
        o.classList.add("fl-standard-knob__dial"), (0, u.defineSvgGradient)("grad__fl-standard-knob__soft-shadow", "radial", {
          cx: .5,
          cy: .5,
          r: .5
        }, {
          "85%": {color: "#242a2e", opacity: .4},
          "100%": {color: "#242a2e", opacity: 0}
        });
        var s = document.createElementNS(u.svgNS, "circle");
        s.classList.add("fl-standard-knob__dial-soft-shadow"), s.setAttribute("cx", 20), s.setAttribute("cy", 20), s.setAttribute("r", 16), s.setAttribute("fill", "url(#grad__fl-standard-knob__soft-shadow)");
        var l = document.createElementNS(u.svgNS, "ellipse");
        l.classList.add("fl-standard-knob__dial-hard-shadow"), l.setAttribute("cx", 20), l.setAttribute("cy", 22), l.setAttribute("rx", 14), l.setAttribute("ry", 14.5), l.setAttribute("fill", "#242a2e"), l.setAttribute("opacity", .15), (0, u.defineSvgGradient)("grad__fl-standard-knob__dial-base", "linear", {
          x1: 0,
          y1: 0,
          x2: 0,
          y2: 1
        }, {"0%": "#52595f", "100%": "#2b3238"});
        var c = document.createElementNS(u.svgNS, "circle");
        c.classList.add("fl-standard-knob__dial-base"), c.setAttribute("cx", 20), c.setAttribute("cy", 20), c.setAttribute("r", 14), c.setAttribute("fill", "url(#grad__fl-standard-knob__dial-base)"), c.setAttribute("stroke", "#242a2e"), c.setAttribute("stroke-width", 1.5), (0, u.defineSvgGradient)("grad__fl-standard-knob__dial-highlight", "linear", {
          x1: 0,
          y1: 0,
          x2: 0,
          y2: 1
        }, {
          "0%": {color: "#70777d", opacity: 1},
          "40%": {color: "#70777d", opacity: 0},
          "55%": {color: "#70777d", opacity: 0},
          "100%": {color: "#70777d", opacity: .3}
        });
        var d = document.createElementNS(u.svgNS, "circle");
        d.classList.add("fl-standard-knob__dial-highlight-stroke"), d.setAttribute("cx", 20), d.setAttribute("cy", 20), d.setAttribute("r", 13), d.setAttribute("fill", "transparent"), d.setAttribute("stroke", "url(#grad__fl-standard-knob__dial-highlight)"), d.setAttribute("stroke-width", 1.5);
        var h = document.createElementNS(u.svgNS, "circle");
        h.classList.add("fl-standard-knob__dial-highlight"), h.setAttribute("cx", 20), h.setAttribute("cy", 20), h.setAttribute("r", 14), h.setAttribute("fill", "#ffffff");
        var f;
        return t && ((f = document.createElementNS(u.svgNS, "circle")).classList.add("fl-standard-knob__indicator-dot"), f.setAttribute("cx", 20), f.setAttribute("cy", 30), f.setAttribute("r", 1.5), f.setAttribute("fill", e)), o.appendChild(s), o.appendChild(l), o.appendChild(c), o.appendChild(d), o.appendChild(h), t && o.appendChild(f), i.appendChild(r), i.appendChild(n), i.appendChild(a), i.appendChild(o), i
      }
    }, {
      key: "_getVisualSetupFunction", value: function (t) {
        return function () {
          this.indicatorRing = this.element.querySelector(".fl-standard-knob__indicator-ring");
          var e = getComputedStyle(this.element.querySelector(".fl-standard-knob__indicator-ring-bg"));
          this.r = parseFloat(e.r) - parseFloat(e.strokeWidth) / 2, t && (this.indicatorDot = this.element.querySelector(".fl-standard-knob__indicator-dot"), this.indicatorDot.style["".concat(this.transformProperty, "Origin")] = "20px 20px")
        }
      }
    }, {
      key: "_getVisualUpdateFunction", value: function (t, e) {
        return function (i) {
          var r = 2 * Math.PI * i + .5 * Math.PI, n = this.r * Math.cos(r) + 20,
            a = this.r * Math.sin(r) + 20;
          switch (e) {
            case"positive":
            default:
              this.indicatorRing.setAttribute("d", "M20,20l0,".concat(this.r).concat(i > .5 ? "A".concat(this.r, ",").concat(this.r, ",0,0,1,20,").concat(20 - this.r) : "", "A-").concat(this.r, ",").concat(this.r, ",0,0,1,").concat(n, ",").concat(a, "Z"));
              break;
            case"negative":
              this.indicatorRing.setAttribute("d", "M20,20l0,".concat(this.r).concat(i < .5 ? "A-".concat(this.r, ",").concat(this.r, ",0,0,0,20,").concat(20 - this.r) : "", "A").concat(this.r, ",").concat(this.r, ",0,0,0,").concat(n, ",").concat(a, "Z"));
              break;
            case"split":
              this.indicatorRing.setAttribute("d", "M20,20l0,-".concat(this.r, "A").concat(this.r, ",").concat(this.r, ",0,0,").concat(i < .5 ? 0 : 1, ",").concat(n, ",").concat(a, "Z"))
          }
          t && (this.indicatorDot.style[this.transformProperty] = "rotate(".concat(360 * i, "deg)"))
        }
      }
    }]), e
  }();
  e.default = f
}, function (t, e) {
}, function (t, e, i) {
  "use strict";

  function r(t) {
    return t && t.__esModule ? t : {default: t}
  }

  function n(t) {
    return (n = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (t) {
      return typeof t
    } : function (t) {
      return t && "function" == typeof Symbol && t.constructor === Symbol && t !== Symbol.prototype ? "symbol" : typeof t
    })(t)
  }

  function a(t, e) {
    if (!(t instanceof e)) throw new TypeError("Cannot call a class as a function")
  }

  function o(t, e) {
    for (var i = 0; i < e.length; i++) {
      var r = e[i];
      r.enumerable = r.enumerable || !1, r.configurable = !0, "value" in r && (r.writable = !0), Object.defineProperty(t, r.key, r)
    }
  }

  function s(t, e, i) {
    return e && o(t.prototype, e), i && o(t, i), t
  }

  function l(t, e) {
    if (e && ("object" === n(e) || "function" == typeof e)) return e;
    if (!t) throw new ReferenceError("this hasn't been initialised - super() hasn't been called");
    return t
  }

  function c(t, e) {
    if ("function" != typeof e && null !== e) throw new TypeError("Super expression must either be null or a function");
    t.prototype = Object.create(e && e.prototype, {
      constructor: {
        value: t,
        enumerable: !1,
        writable: !0,
        configurable: !0
      }
    }), e && (Object.setPrototypeOf ? Object.setPrototypeOf(t, e) : t.__proto__ = e)
  }

  Object.defineProperty(e, "__esModule", {value: !0}), e.default = void 0, i(10);
  var u = i(5), d = r(i(4)), h = r(i(0)), f = 0, p = function (t) {
    return 1 - Math.cos(t * Math.PI / 2)
  }, v = function (t) {
    return Math.sin(t * Math.PI / 2)
  }, g = Math.PI / 2, m = function (t, e) {
    return 20 + t * Math.cos(g + e)
  }, _ = function (t, e) {
    return 20 + t * Math.sin(g + e)
  }, b = function (t) {
    function e(t) {
      var i,
        r = arguments.length > 1 && void 0 !== arguments[1] ? arguments[1] : {};
      if (a(this, e), !t) throw new Error("FLReactiveGripDial constructor must receive a valid container element");
      var n = void 0 !== r.color ? r.color : d.default.default.str,
        o = "number" == typeof r.guideTicks ? r.guideTicks : 9,
        s = "number" == typeof r.gripBumps ? r.gripBumps : 5,
        c = "number" == typeof r.gripExtrusion ? r.gripExtrusion : .5,
        u = "number" == typeof r.minRotation ? r.minRotation : .5 / o * 360,
        h = "number" == typeof r.maxRotation ? r.maxRotation : 360 * (1 - .5 / o),
        f = e._constructVisualElement(n, o, u, h);
      return r.visualContext = e._getVisualSetupFunction(u, h), r.updateVisuals = e._getVisualUpdateFunction(), t.classList.add("fl-reactive-grip-dial"), t.appendChild(f), i = l(this, (e.__proto__ || Object.getPrototypeOf(e)).call(this, t, f, r)), i.gripBumps = s, i.gripExtrusion = c, i.mouseX = 0, i.mouseY = 0, i.hoverTween = {
        rafId: null,
        direction: 1,
        progress: 0,
        startTime: 0,
        duration: 600
      }, i._reactiveDialHandlers = {
        hover: i.handleHover.bind(i),
        move: i.handleMove.bind(i),
        unhover: i.handleUnhover.bind(i),
        dragStart: i.handleDragStart.bind(i),
        dragEnd: i.handleDragEnd.bind(i)
      }, i.addEventListener("mouseover", i._reactiveDialHandlers.hover), i.addEventListener("knobdragstart", i._reactiveDialHandlers.dragStart), i
    }

    return c(e, h.default), s(e, [{
      key: "handleHover", value: function (t) {
        this.mouseX = t.clientX, this.mouseY = t.clientY, this.startHoverEffect()
      }
    }, {
      key: "handleMove", value: function (t) {
        this.mouseX = t.clientX, this.mouseY = t.clientY;
        var e = this._input.getBoundingClientRect();
        (t.clientX < e.left || t.clientX > e.right || t.clientY < e.top || t.clientY > e.bottom) && this.stopHoverEffect()
      }
    }, {
      key: "handleUnhover", value: function (t) {
        this.stopHoverEffect()
      }
    }, {
      key: "handleDragStart", value: function (t) {
        this.startHoverEffect()
      }
    }, {
      key: "handleDragEnd", value: function (t) {
        this.stopHoverEffect()
      }
    }, {
      key: "startHoverEffect", value: function () {
        document.body.addEventListener("mousemove", this._reactiveDialHandlers.move), this.addEventListener("mouseout", this._reactiveDialHandlers.unhover), this.addEventListener("knobdragend", this._reactiveDialHandlers.dragEnd), this.hoverTween.rafId && window.cancelAnimationFrame(this.hoverTween.rafId), this.hoverTween = {
          rafId: window.requestAnimationFrame(this.tickHoverTween.bind(this)),
          direction: 1,
          duration: 300,
          startProgress: this.hoverTween.progress
        }
      }
    }, {
      key: "stopHoverEffect", value: function () {
        var t = this._input.getBoundingClientRect();
        if (this.mouseX >= t.left && this.mouseX <= t.right && this.mouseY >= t.top && this.mouseY <= t.bottom || this._activeDrag) return !1;
        document.body.removeEventListener("mousemove", this._reactiveDialHandlers.move), this.removeEventListener("mouseout", this._reactiveDialHandlers.unhover), this.removeEventListener("knobdragend", this._reactiveDialHandlers.dragEnd), this.hoverTween.rafId && window.cancelAnimationFrame(this.hoverTween.rafId), this.hoverTween = {
          rafId: window.requestAnimationFrame(this.tickHoverTween.bind(this)),
          direction: -1,
          duration: 600,
          startProgress: this.hoverTween.progress
        }
      }
    }, {
      key: "tickHoverTween", value: function (t) {
        this.hoverTween.startTime || (this.hoverTween.startTime = t), this.hoverTween.progress = (t - this.hoverTween.startTime) / this.hoverTween.duration, this.hoverTween.direction > 0 ? (this.hoverTween.progress *= 1 - this.hoverTween.startProgress, this.hoverTween.progress += this.hoverTween.startProgress, this.hoverTween.progress < 1 ? (this.morphGripShape(v(this.hoverTween.progress)), this.hoverTween.rafId = window.requestAnimationFrame(this.tickHoverTween.bind(this))) : (this.hoverTween.progress = 1, this.morphGripShape(1), this.hoverTween.rafId = null)) : (this.hoverTween.progress *= this.hoverTween.startProgress, this.hoverTween.progress = this.hoverTween.startProgress - this.hoverTween.progress, this.hoverTween.progress > 0 ? (this.morphGripShape(p(this.hoverTween.progress)), this.hoverTween.rafId = window.requestAnimationFrame(this.tickHoverTween.bind(this))) : (this.hoverTween.progress = 0, this.morphGripShape(0), this.hoverTween.rafId = null))
      }
    }, {
      key: "morphGripShape", value: function (t) {
        for (var e = Math.PI / this.gripBumps, i = (2 - t) * e, r = t * e, n = 13 / (18 * this.gripExtrusion + 1) * this.gripBumps, a = "M".concat(m(13, -i / 2), ",").concat(_(13, -i / 2)), o = 0; o < this.gripBumps; o++) {
          var s = 2 * o * e + i / 2, l = (2 * o + 1) * e + r / 2;
          a += "A-13,13,0,0,1,".concat(m(13, s), ",").concat(_(13, s)), a += "A-".concat(n, ",").concat(n, ",0,0,0,").concat(m(13, l), ",").concat(_(13, l))
        }
        a += "Z", this._visualContext.gripMask.setAttribute("d", a), this._visualContext.gripOutline.setAttribute("d", a)
      }
    }], [{
      key: "_constructVisualElement", value: function (t, e, i, r) {
        var n = document.createElementNS(u.svgNS, "svg");
        n.classList.add("fl-reactive-grip-dial__svg"), n.setAttribute("viewBox", "0 0 40 40");
        var a = document.createElementNS(u.svgNS, "defs"),
          o = document.createElementNS(u.svgNS, "mask");
        o.id = "mask__fl-reactive-grip__grip-outline--".concat(f++);
        var s = (0, u.createPath)("M20,33A13,13,0,0,1,20,7A-13,13,0,0,1,20,33Z", {
          classes: "fl-reactive-grip-dial__grip-mask-path",
          fill: "#ffffff"
        });
        o.appendChild(s), a.appendChild(o);
        for (var l = i * Math.PI / 180, c = r * Math.PI / 180, d = c - l, h = (0, u.createGroup)({classes: "fl-reactive-grip-dial__guides"}), p = (0, u.createPath)("M".concat(m(16, l), ",").concat(_(16, l), "A16,16,0,0,1,20,4A-16,16,0,0,1,").concat(m(16, c), ",").concat(_(16, c)), {
          classes: "fl-reactive-grip-dial__focus-indicator",
          stroke: t,
          strokeWidth: 3,
          strokeLinecap: "round",
          filter: (0, u.defineBlurFilter)("filter__fl-reactive-grip-dial__blur-focus-indicator", 1.5, "none", .2)
        }), v = (0, u.createPath)("M".concat(m(16, l), ",").concat(_(16, l), "A16,16,0,0,1,20,4A-16,16,0,0,1,").concat(m(16, c), ",").concat(_(16, c)), {
          classes: "fl-reactive-grip-dial__guide-ring",
          stroke: "#32383c",
          strokeWidth: 3,
          strokeLinecap: "round"
        }), g = [], b = 0; b < e; b++) {
          var y = l + b * d / (e - 1);
          g.push((0, u.createLine)(m(19.5, y), _(19.5, y), m(14.5, y), _(14.5, y), {
            classes: "fl-reactive-grip-dial__guide-tick",
            stroke: "#23292d"
          }))
        }
        h.appendChild(p), h.appendChild(v), g.forEach(function (t) {
          return h.appendChild(t)
        });
        var k = (0, u.createGroup)({
            classes: "fl-reactive-grip-dial__grip",
            filter: (0, u.defineDropshadowFilter)("filter__fl-reactive-grip-dial__drop-shadow", 2304301, .3, 0, 2, .3)
          }), w = (0, u.createRectangle)(6, 6, 28, 28, {
            classes: "fl-reactive-grip-dial__grip-fill",
            fill: (0, u.defineSvgGradient)("grad__fl-reactive-grip-dial__grip-fill", "radial", {
              cx: .5,
              cy: -.2,
              r: 1.2,
              fx: .5,
              fy: -.2
            }, {"0%": "#8b9499", "70%": "#10191e", "100%": "#2b3439"}),
            mask: "url(#".concat(o.id, ")")
          }),
          E = (0, u.createPath)("M20,33A13,13,0,0,1,20,7A-13,13,0,0,1,20,33Z", {
            classes: "fl-reactive-grip-dial__grip-outline",
            stroke: "#23292d",
            strokeWidth: .5
          }), C = (0, u.createCircle)(m(10.5, 0), _(10.5, 0), 1, {
            classes: "fl-reactive-grip-dial__indicator-dot",
            fill: t
          });
        k.appendChild(w), k.appendChild(E), k.appendChild(C);
        var A = (0, u.createGroup)({classes: "fl-reactive-grip-dial__chrome"}),
          S = (0, u.defineBlurFilter)("filter__fl-reactive-grip-dial__blur-base", 1.5),
          T = (0, u.defineBlurFilter)("filter__fl-reactive-grip-dial__blur-base", .5),
          x = {
            "0%": {color: "#ffffff", opacity: 0},
            "100%": {color: "#ffffff", opacity: .12}
          },
          L = (0, u.defineSvgGradient)("grad__fl-reactive-grip-dial__gradient-a", "linear", {
            x1: 0,
            y1: 0,
            x2: 0,
            y2: 1
          }, x),
          M = (0, u.defineSvgGradient)("grad__fl-reactive-grip-dial__gradient-b", "linear", {
            x1: 0,
            y1: 1,
            x2: 0,
            y2: 0
          }, x),
          D = (0, u.defineSvgGradient)("grad__fl-reactive-grip-dial__gradient-c", "linear", {
            x1: 0,
            y1: 0,
            x2: 1,
            y2: 0
          }, x),
          P = (0, u.defineSvgGradient)("grad__fl-reactive-grip-dial__gradient-d", "linear", {
            x1: 1,
            y1: 0,
            x2: 0,
            y2: 0
          }, x),
          R = (0, u.defineDarkenFilter)("filter__fl-reactive-grip-dial__darken", .75, .05),
          O = (0, u.createGroup)({
            classes: "fl-reactive-grip-dial__chrome-base",
            mask: (0, u.defineMask)("mask__fl-reactive-grip__chrome-base", [(0, u.createCircle)(20, 20, 8, {fill: "#ffffff"})]),
            transform: "rotate(-25 20 20)"
          }), F = (0, u.createGroup)({filter: S});
        F.appendChild((0, u.createRectangle)(12, 12, 16, 16, {fill: "#383d3f"})), F.appendChild((0, u.createRectangle)(12, 12, 8, 16, {fill: L})), F.appendChild((0, u.createRectangle)(20, 12, 8, 16, {fill: M})), F.appendChild((0, u.createRectangle)(12, 12, 16, 8, {fill: D})), F.appendChild((0, u.createRectangle)(12, 20, 16, 8, {fill: P})), F.appendChild((0, u.createLine)(12, 28, 19, 21, {
          stroke: "#ffffff",
          strokeOpacity: .8
        })), F.appendChild((0, u.createLine)(21, 19, 28, 12, {
          stroke: "#ffffff",
          strokeOpacity: .8
        })), O.appendChild(F), O.appendChild((0, u.createLine)(12, 28, 19.5, 20.5, {
          stroke: "#ffffff",
          strokeOpacity: .5,
          strokeWidth: .75,
          filter: T
        })), O.appendChild((0, u.createLine)(20.5, 19.5, 28, 12, {
          stroke: "#ffffff",
          strokeOpacity: .5,
          strokeWidth: .75,
          filter: T
        }));
        for (var N = [], I = 1; I < 11; I++) N.push((0, u.createCircle)(20, 20, 7.5 * I / 10, {
          stroke: "#ffffff",
          strokeWidth: .375
        }));
        var G = (0, u.createGroup)({
          classes: "fl-reactive-grip-dial__chrome-ridges",
          mask: (0, u.defineMask)("mask__fl-reactive-grip__chrome-ridges", N),
          transform: "rotate(-19 20 20)",
          filter: R
        }), V = (0, u.createGroup)({filter: S});
        V.appendChild((0, u.createRectangle)(12, 12, 16, 16, {fill: "#383d3f"})), V.appendChild((0, u.createRectangle)(12, 12, 8, 16, {fill: L})), V.appendChild((0, u.createRectangle)(20, 12, 8, 16, {fill: M})), V.appendChild((0, u.createRectangle)(12, 12, 16, 8, {fill: D})), V.appendChild((0, u.createRectangle)(12, 20, 16, 8, {fill: P})), V.appendChild((0, u.createLine)(12, 28, 19, 21, {
          stroke: "#ffffff",
          strokeOpacity: .8
        })), V.appendChild((0, u.createLine)(21, 19, 28, 12, {
          stroke: "#ffffff",
          strokeOpacity: .8
        })), G.appendChild(V), G.appendChild((0, u.createLine)(12, 28, 19.5, 20.5, {
          stroke: "#ffffff",
          strokeOpacity: .5,
          strokeWidth: .75,
          filter: T
        })), G.appendChild((0, u.createLine)(20.5, 19.5, 28, 12, {
          stroke: "#ffffff",
          strokeOpacity: .5,
          strokeWidth: .75,
          filter: T
        }));
        var B = (0, u.createCircle)(20, 20, 8, {
          classes: "fl-reactive-grip-dial__chrome-outline",
          stroke: "#23292d"
        }), j = (0, u.createCircle)(20, 20, 7.5, {
          classes: "fl-reactive-grip-dial__chrome-highlight",
          stroke: "#70777d",
          strokeOpacity: .6
        });
        return A.appendChild(O), A.appendChild(G), A.appendChild(B), A.appendChild(j), n.appendChild(a), n.appendChild(h), n.appendChild(k), n.appendChild(A), n
      }
    }, {
      key: "_getVisualSetupFunction", value: function (t, e) {
        return function () {
          this.rotationDelta = e - t, this.minRotation = t, this.gripMask = this.element.querySelector(".fl-reactive-grip-dial__grip-mask-path"), this.gripMask.style["".concat(this.transformProperty, "Origin")] = "20px 20px", this.gripOutline = this.element.querySelector(".fl-reactive-grip-dial__grip-outline"), this.gripOutline.style["".concat(this.transformProperty, "Origin")] = "20px 20px", this.indicatorDot = this.element.querySelector(".fl-reactive-grip-dial__indicator-dot"), this.indicatorDot.style["".concat(this.transformProperty, "Origin")] = "20px 20px"
        }
      }
    }, {
      key: "_getVisualUpdateFunction", value: function () {
        return function (t) {
          var e = this.minRotation + t * this.rotationDelta;
          this.gripMask.style[this.transformProperty] = "rotate(".concat(e, "deg)"), this.gripOutline.style[this.transformProperty] = "rotate(".concat(e, "deg)"), this.indicatorDot.style[this.transformProperty] = "rotate(".concat(e, "deg)")
        }
      }
    }]), e
  }();
  e.default = b
}, function (t, e) {
}]).default;