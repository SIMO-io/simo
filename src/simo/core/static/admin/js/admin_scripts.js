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

            function activateButton($el){
              $el.find('.action').on('click', function(e){
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
                  var sendJson = {};
                  sendJson[$(this).data('method')] = kwargs;
                  controllerSocket.send(
                    JSON.stringify(sendJson)
                  );
                });
            }

            activateButton($element);

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
        e.preventDefault();
        if (confirm("Are you sure you want to UPDATE your hub?")){
          window.location = this.href;
        }
    });

    $('#reboot_link').click(function(e){
        e.preventDefault();
        if (confirm("Are you sure you want to REBOOT your hub?")){
          window.location = this.href;
        }
    });




})(django.jQuery);
