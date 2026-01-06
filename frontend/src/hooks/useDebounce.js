import { useState, useEffect } from 'react'

/**
 * useDebounce - Custom hook for debouncing values
 *
 * Delays updating the debounced value until after the specified delay
 * has passed without the value changing. Useful for search inputs and
 * other scenarios where you want to wait for the user to stop typing.
 *
 * @param {any} value - The value to debounce
 * @param {number} delay - Delay in milliseconds (default: 300)
 * @returns {any} - The debounced value
 *
 * @example
 * const [searchTerm, setSearchTerm] = useState('')
 * const debouncedSearchTerm = useDebounce(searchTerm, 500)
 *
 * // debouncedSearchTerm will only update 500ms after user stops typing
 * useEffect(() => {
 *   // Fetch results using debouncedSearchTerm
 * }, [debouncedSearchTerm])
 */
export function useDebounce(value, delay = 300) {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    // Set a timeout to update the debounced value after the delay
    const handler = setTimeout(() => {
      setDebouncedValue(value)
    }, delay)

    // Cleanup function: cancel the timeout if value changes before delay expires
    return () => {
      clearTimeout(handler)
    }
  }, [value, delay]) // Re-run effect when value or delay changes

  return debouncedValue
}
