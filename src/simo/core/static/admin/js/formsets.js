$(document).ready(function(){
    $('.formset-container .addlink').click(function(e){
        e.preventDefault();
        var $form_container = $(this).closest('.formset-container');
        var prefix = $form_container.data('prefix');
        var current_forms_count = parseInt($('#id_' + prefix + '-TOTAL_FORMS').val());
        $('#id_' + prefix + '-TOTAL_FORMS').val(current_forms_count + 1);

        var newFormRow = $form_container.find('.form-row')[0].cloneNode(true);
        var formRegex = RegExp(prefix + '-(\\d){1}-','g');

        newFormRow.innerHTML = newFormRow.innerHTML.replace(
            formRegex, prefix + '-' + current_forms_count + '-'
        );
        $form_container.find('table').append(newFormRow);

    });
});
