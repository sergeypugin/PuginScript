(program
  (def print64
    (param str label)
    (param int[] val)
    (block
      (expr (call println (+ (+ (+ (identifier label) (index (identifier val) 0)) " ") (index (identifier val) 1))))))
  (def add64
    (param int[] a)
    (param int[] b)
    (returns int[])
    (block
      (var_decl int[] res (new int 2))
      (assign (lv res 1) = (+ (index (identifier a) 1) (index (identifier b) 1)))
      (assign (lv res 0) = (+ (index (identifier a) 0) (index (identifier b) 0)))
      (var_decl bool carry false)
      (if (< (index (identifier a) 1) 0)
        (block
          (if (| (< (index (identifier b) 1) 0) (>= (index (identifier res) 1) 0))
            (block
              (assign (lv carry) = true))))
        (else
          (if (& (< (index (identifier b) 1) 0) (>= (index (identifier res) 1) 0))
            (block
              (assign (lv carry) = true)))))
      (if (identifier carry)
        (block
          (assign (lv res 0) += 1)))
      (return (identifier res))))
  (def sub64
    (param int[] a)
    (param int[] b)
    (returns int[])
    (block
      (var_decl int[] res (new int 2))
      (assign (lv res 1) = (- (index (identifier a) 1) (index (identifier b) 1)))
      (assign (lv res 0) = (- (index (identifier a) 0) (index (identifier b) 0)))
      (var_decl bool borrow false)
      (if (>= (index (identifier a) 1) 0)
        (block
          (if (| (< (index (identifier b) 1) 0) (< (index (identifier a) 1) (index (identifier b) 1)))
            (block
              (assign (lv borrow) = true))))
        (else
          (if (& (< (index (identifier b) 1) 0) (< (index (identifier a) 1) (index (identifier b) 1)))
            (block
              (assign (lv borrow) = true)))))
      (if (identifier borrow)
        (block
          (assign (lv res 0) -= 1)))
      (return (identifier res))))
  (def main
    (block
      (expr (call println "64-bit arithmetic example\n"))
      (expr (call println "32-bit range: -2_147_483_648 to 2_147_483_647"))
      (expr (call println "64-bit range: -9_223_372_036_854_775_808 to 9_223_372_036_854_775_807"))
      (expr (call println))
      (var_decl int[] a (new int 2))
      (var_decl int[] b (new int 2))
      (expr (call println "Enter A (high then low):"))
      (assign (lv a 0) = (call input_int))
      (assign (lv a 1) = (call input_int))
      (expr (call println "Enter B (high then low):"))
      (assign (lv b 0) = (call input_int))
      (assign (lv b 1) = (call input_int))
      (expr (call print64 "Sum: " (call add64 (identifier a) (identifier b))))
      (expr (call print64 "Diff: " (call sub64 (identifier a) (identifier b)))))))