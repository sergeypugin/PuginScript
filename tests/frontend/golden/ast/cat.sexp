(program
  (while true
    (block
      (var_decl int char (call input_char))
      (expr (call print_char (identifier char))))))