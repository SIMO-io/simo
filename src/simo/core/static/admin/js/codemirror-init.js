(function($) {
    'use strict';

    var init = function(element, options) {
        var settings = $.extend({
          lineNumbers: true,
          styleActiveLine:true,
          matchBrackets: true,
          theme: 'lucario',
          mode: 'python',
          indentUnit: 4,
          lineWrapping: true,
          extraKeys: {
            "Tab": function(cm){
              cm.replaceSelection("    " , "end");
            }
          }
        }, options);

        var editor = CodeMirror.fromTextArea(
          element, settings
        );
        editor.setSize(650, "100%");
        editor.on('change', function(editor){
          $(element).val(editor.doc.getValue());
        });
    };

    $.fn.PythonCodemirror = function(options) {
        var settings = $.extend({}, options);
        $.each(this, function(i, element) {
            init(element, settings);
        });
        return this;
    };

    $(function() {
        // Initialize all autocomplete widgets except the one in the template
        // form used when a new formset is added.
        $('.python-code').not('[name*=__prefix__]').PythonCodemirror();
    });

    $(document).on('formset:added', (function() {
        return function(event, $newFormset) {
            return $newFormset.find('.python-code').PythonCodemirror();
        };
    })(this));
}(django.jQuery));
