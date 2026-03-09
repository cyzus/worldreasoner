import { useState, useEffect, useRef } from 'react'

export const useDraggablePopup = (node) => {
    const [position, setPosition] = useState({ x: 0, y: 0 })
    const [isDragging, setIsDragging] = useState(false)
    const dragOffset = useRef({ x: 0, y: 0 })

    // Initialize position when node changes (Smart Positioning)
    useEffect(() => {
        if (!node) return
        const screenX = node._screenX || 0
        const screenY = node._screenY || 0

        // Constants
        const POPUP_WIDTH = 320
        const POPUP_EST_HEIGHT = 400
        const PADDING = 20
        const WINDOW_W = window.innerWidth
        const WINDOW_H = window.innerHeight

        let x = screenX + 60
        let y = screenY - 100

        // Clamp X (Right Edge)
        if (x + POPUP_WIDTH > WINDOW_W - PADDING) {
            x = WINDOW_W - POPUP_WIDTH - PADDING
        }
        // Clamp X (Left Edge)
        x = Math.max(PADDING, x)

        // Clamp Y (Bottom Edge)
        if (y + POPUP_EST_HEIGHT > WINDOW_H - PADDING) {
            y = WINDOW_H - POPUP_EST_HEIGHT - PADDING
        }
        // Clamp Y (Top Edge)
        y = Math.max(PADDING + 60, y)

        setPosition({ x, y })
    }, [node?.id, node?._screenX, node?._screenY])

    // Handle dragging
    useEffect(() => {
        if (!isDragging) return

        const handleMouseMove = (e) => {
            setPosition({
                x: e.clientX - dragOffset.current.x,
                y: e.clientY - dragOffset.current.y
            })
        }

        const handleMouseUp = () => {
            setIsDragging(false)
        }

        window.addEventListener('mousemove', handleMouseMove)
        window.addEventListener('mouseup', handleMouseUp)

        return () => {
            window.removeEventListener('mousemove', handleMouseMove)
            window.removeEventListener('mouseup', handleMouseUp)
        }
    }, [isDragging])

    const handleMouseDown = (e) => {
        // Only allow dragging from header (excluding close button)
        if (e.target.closest('.close-btn')) return

        setIsDragging(true)
        dragOffset.current = {
            x: e.clientX - position.x,
            y: e.clientY - position.y
        }
    }

    return { position, isDragging, handleMouseDown }
}
