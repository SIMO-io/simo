(function($) {
    'use strict';

    var init = function($element, options) {
        var ws_url = $element.data('ws_url');
        var $log_container = $element.find('.log-container');
        var $clear_btn = $element.find('button');
        if (ws_url === ''){
            return;
        }
        var first_load = true;
        var socket_proto = 'ws://';
        if (location.protocol === 'https:'){
            socket_proto = 'wss://';
        }
        var logSocket = new WebSocket(
          socket_proto + window.location.host + ws_url
        );
        logSocket.onmessage = function(e){
            // Scroll down if scroller is already at the bottom.
            var scroll = false;
            if ($log_container.find('.scroller').height() === $log_container.scrollTop() + $log_container.height()){
                scroll = true;
            }
            $log_container.find('.scroller').append(e.data);
            if (scroll || first_load){
                $log_container.animate(
                  {scrollTop: $log_container.find('.scroller').height()}, 50
                );
            }
            first_load = false;
        };
        $clear_btn.click(function(e){
            e.preventDefault();
            logSocket.send("clear");
            $log_container.find('.scroller').html('');
        });
    };

    $.fn.CodeLog = function(options) {
        var settings = $.extend({}, options);
        $.each(this, function(i, element) {
            var $element = $(element);
            init($element, settings);
        });
        return this;
    };

    $(function() {
        // Initialize all autocomplete widgets except the one in the template
        // form used when a new formset is added.+
        $('.code-log').not('[name*=__prefix__]').CodeLog();
    });

    $(document).on('formset:added', (function() {
        return function(event, $newFormset) {
            return $newFormset.find('.code-log').CodeLog();
        };
    })(this));
}(django.jQuery));
