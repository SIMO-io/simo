(function($) {

    $.fn.ComponentController = function(options) {
        var settings = $.extend({}, options);
        $.each(this, function(i, element) {

            var ws_url = $(element).data('ws_url');
            if (ws_url === ''){
                return;
            }

            var $element = $(element);

            var socket_proto = 'ws://';
            if (location.protocol === 'https:'){
                socket_proto = 'wss://';
            }
            var socket_url = socket_proto + window.location.host + ws_url;
            var controllerSocket = new WebSocket(socket_url);
            var eventNs = '.componentController' + Math.random().toString(36).slice(2);
            var pressActive = false;
            var holdSent = false;
            var awaitingSecondTap = false;
            var holdTimer = null;
            var clickTimer = null;
            var activeMomentaryConfig = null;

            function sendAction(method, value, kwargs){
                if (!method){
                    return;
                }
                var sendJson = {};
                if (value !== undefined){
                    sendJson[method] = [value];
                } else if (kwargs !== undefined){
                    sendJson[method] = kwargs;
                } else {
                    sendJson[method] = {};
                }
                controllerSocket.send(JSON.stringify(sendJson));
            }

            function clearHoldTimer(){
                if (holdTimer){
                    clearTimeout(holdTimer);
                    holdTimer = null;
                }
            }

            function extractMomentaryConfig($node){
                return {
                    pressMethod: $node.data('pressMethod'),
                    pressValue: $node.data('pressValue'),
                    releaseMethod: $node.data('releaseMethod'),
                    releaseValue: $node.data('releaseValue'),
                    holdMethod: $node.data('holdMethod'),
                    holdValue: $node.data('holdValue'),
                    clickMethod: $node.data('clickMethod'),
                    clickValue: $node.data('clickValue'),
                    doubleMethod: $node.data('doubleMethod'),
                    doubleValue: $node.data('doubleValue'),
                    doubleDelay: parseInt($node.data('doubleDelay') || 350, 10),
                    holdDelay: parseInt($node.data('holdDelay') || 1000, 10)
                };
            }

            function sendMomentary(kind, config){
                config = config || activeMomentaryConfig;
                if (!config){
                    return;
                }
                var method = config[kind + 'Method'];
                if (!method){
                    return;
                }
                var value = config[kind + 'Value'];
                sendAction(method, value);
            }

            function activateButton($el){
              $el.find('.action').not('.momentary-action').on('click', function(e){
                  e.preventDefault();
                  $(this).attr('disabled', 'disabled');
                  $(this).addClass('disabled');
                  var kwargs = {};
                  $.each($(this).data(), function(key, val){
                      if (key.substring(key.length - 5) === '_node'){
                          kwargs[key.substring(0, key.length - 5)] = $('#' + val).val();
                      }else if (key !== 'method'){
                          kwargs[key] = val;
                      }
                  });
                  sendAction($(this).data('method'), undefined, kwargs);
                });

              $el.find('.momentary-action').on('pointerdown', function(e){
                  e.preventDefault();
                  if (pressActive){
                      return;
                  }

                  activeMomentaryConfig = extractMomentaryConfig($(this));
                  holdSent = false;
                  awaitingSecondTap = !!clickTimer;
                  if (clickTimer){
                      clearTimeout(clickTimer);
                      clickTimer = null;
                  }
                  pressActive = true;
                  sendMomentary('press', activeMomentaryConfig);

                  clearHoldTimer();
                  holdTimer = setTimeout(function(){
                      if (!pressActive || holdSent){
                          return;
                      }
                      holdSent = true;
                      sendMomentary('hold', activeMomentaryConfig);
                  }, activeMomentaryConfig.holdDelay);

                  try {
                      if (this.setPointerCapture && e.originalEvent.pointerId !== undefined){
                          this.setPointerCapture(e.originalEvent.pointerId);
                      }
                  } catch (err) {}
                });
            }

            function finishMomentaryPress(e){
                if (!pressActive){
                    return;
                }
                if (e){
                    e.preventDefault();
                }

                var config = activeMomentaryConfig;
                pressActive = false;
                clearHoldTimer();
                sendMomentary('release', config);

                if (holdSent){
                    holdSent = false;
                    awaitingSecondTap = false;
                    return;
                }

                if (awaitingSecondTap){
                    awaitingSecondTap = false;
                    sendMomentary('double', config);
                    return;
                }

                clickTimer = setTimeout(function(){
                    sendMomentary('click', config);
                    clickTimer = null;
                }, (config && config.doubleDelay) || 350);
            }

            activateButton($element);
            $(document).off('pointerup' + eventNs + ' pointercancel' + eventNs);
            $(document).on('pointerup' + eventNs + ' pointercancel' + eventNs, function(e){
                finishMomentaryPress(e);
            });

            controllerSocket.onmessage = function(e){
                $element.html(e.data);
                activateButton($element);
            };
        });
        return this;
    };

    $(function() {
        // Initialize all autocomplete widgets except the one in the template
        // form used when a new formset is added.+
        $('.component-controller').not('[name*=__prefix__]').ComponentController();
    });

    $(document).on('formset:added', (function() {
        return function(event, $newFormset) {
            return $newFormset.find('.component-controller').ComponentController();
        };
    })(this));

    $.fn.KnobController = function(options) {
        var settings = $.extend({}, options);
        $.each(this, function(i, element) {

            var knob = new PrecisionInputs.FLStandardKnob(element, {
                color: '#79aec8',
                initial: parseFloat($(element).data('value')),
                min: parseFloat($(element).data('min')),
                max: parseFloat($(element).data('max')),
                step: 0.01
            });

            var socket_proto = 'ws://';
            if (location.protocol === 'https:'){
                socket_proto = 'wss://';
            }

            var ws_url = $(element).data('ws_url');
            if (ws_url === ''){
                return;
            }

            var controllerSocket = new WebSocket(
               socket_proto + window.location.host + ws_url
            );
            controllerSocket.onopen = function(e){
                controllerSocket.send(JSON.stringify({send_value:true}));
            };
            controllerSocket.onmessage = function(e){
                knob.value = parseFloat(JSON.parse(e.data).value);
            };
            knob.addEventListener('knobdragend', function(evt) {
              controllerSocket.send(
                JSON.stringify(
                  {'send': [parseFloat(evt.target.value)]}
                  )
              );
            });
        });
        return this;
    };

    $(function() {
        // Initialize all autocomplete widgets except the one in the template
        // form used when a new formset is added.+
        $('.knob').not('[name*=__prefix__]').KnobController();
    });

    $(document).on('formset:added', (function() {
        return function(event, $newFormset) {
            return $newFormset.find('.knob').KnobController();
        };
    })(this));

    $('.dropbtn').click(function(e){
        $(this).closest('.dropdown-menu').find('.dropdown-content').toggleClass('show');
    });

    window.onclick = function(event) {
      var closest_btn =  $(event.target).closest('.dropbtn');

      if (closest_btn.length === 0){
        var dropdowns = document.getElementsByClassName("dropdown-content");
        var i;
        for (i = 0; i < dropdowns.length; i++) {
          var openDropdown = dropdowns[i];
          if (openDropdown.classList.contains('show')) {
            openDropdown.classList.remove('show');
          }
        }
      } else {
          var this_dd = closest_btn.closest('.dropdown-menu').find('.dropdown-content').get(0);
          $('.dropdown-content').each(function(index){
              if (this_dd !== this){
                  $(this).removeClass('show');
              }
          });
      }

    };

    $('.update_link').click(function(e){
        if (!confirm("Are you sure you want to UPDATE your hub?")){
          e.preventDefault();
          e.stopPropagation();
        }
    });

    $('#reboot_link').click(function(e){
        // If this is a POST form button with onsubmit confirmation,
        // do not interfere (avoids navigating to "undefined").
        var $form = $(this).closest('form');
        if ($form.length && $form.attr('onsubmit')){
          return;
        }

        if (!confirm("Are you sure you want to REBOOT your hub?")){
          e.preventDefault();
          e.stopPropagation();
        }
    });




})(django.jQuery);
