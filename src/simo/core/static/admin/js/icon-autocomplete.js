(function($) {
    'use strict';

    function iconDisplayTemplate(result){
        return $('<span><span class="icon-img" style="background: url(/icon/' + result.id + '/);"></span>' + result.text + '</span>');
    }

    var init = function($element, options) {
        var settings = $.extend({
            ajax: {
                data: function(params) {
                    return {
                        term: params.term,
                        page: params.page
                    };
                }
            },
            templateResult: iconDisplayTemplate,
            templateSelection: iconDisplayTemplate,
            width: '260px',
        }, options);
        $element.select2(settings);
    };

    $.fn.IconSelect2 = function(options) {
        var settings = $.extend({}, options);
        $.each(this, function(i, element) {
            var $element = $(element);
            init($element, settings);
        });
        return this;
    };

    $(function() {
        // Initialize all autocomplete widgets except the one in the template
        // form used when a new formset is added.
        $('.icon-autocomplete').not('[name*=__prefix__]').IconSelect2();
    });

    $(document).on('formset:added', (function() {
        return function(event, $newFormset) {
            return $newFormset.find('.icon-autocomplete').IconSelect2();
        };
    })(this));
}(django.jQuery));
