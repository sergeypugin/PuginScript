(program
  (var_decl int count (call input_int))
  (if (<= (identifier count) 0)
    (block
      (expr (call println (- 1))))
    (else
      (block
        (var_decl int i 0)
        (while (< (identifier i) (identifier count))
          (block
            (var_decl int base (call input_int))
            (var_decl int exp (call input_int))
            (if (< (identifier exp) 0)
              (block
                (expr (call println (- 1))))
              (else
                (block
                  (expr (call println (** (identifier base) (identifier exp)))))))
            (assign (lv i) = (+ (identifier i) 1))))))))
