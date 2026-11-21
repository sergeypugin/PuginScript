(program
  (def match
    (param str pattern)
    (param str text)
    (param int pattern_index)
    (param int text_index)
    (returns bool)
    (block
      (var_decl bool matched false)
      (if (== (index (identifier pattern) (identifier pattern_index)) (char 0))
        (block
          (assign (lv matched) = (== (index (identifier text) (identifier text_index)) (char 0))))
        (else
          (if (== (index (identifier pattern) (identifier pattern_index)) (char 42))
            (block
              (if (call match (identifier pattern) (identifier text) (+ (identifier pattern_index) 1) (identifier text_index))
                (block
                  (assign (lv matched) = true))
                (else
                  (if (!= (index (identifier text) (identifier text_index)) (char 0))
                    (block
                      (assign (lv matched) = (call match (identifier pattern) (identifier text) (identifier pattern_index) (+ (identifier text_index) 1))))))))
            (else
              (if (!= (index (identifier text) (identifier text_index)) (char 0))
                (block
                  (if (| (== (index (identifier pattern) (identifier pattern_index)) (char 63)) (== (index (identifier pattern) (identifier pattern_index)) (index (identifier text) (identifier text_index))))
                    (block
                      (assign (lv matched) = (call match (identifier pattern) (identifier text) (+ (identifier pattern_index) 1) (+ (identifier text_index) 1)))))))))))
      (return (identifier matched))))
  (var_decl str pattern (call input))
  (var_decl str text (call input))
  (if (call match (identifier pattern) (identifier text) 0 0)
    (block
      (expr (call println 1)))
    (else
      (block
        (expr (call println 0))))))
