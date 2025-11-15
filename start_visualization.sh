#!/bin/bash
# WorldReasoner Graph Visualization Startup Script
# Starts both backend and frontend

echo -e "\033[36mStarting WorldReasoner Graph Visualization...\033[0m"

# Check if backend dependencies are installed
echo -e "\n\033[33mChecking backend dependencies...\033[0m"
if uv sync; then
    echo -e "\033[32mBackend dependencies OK\033[0m"
else
    echo -e "\033[31mFailed to install backend dependencies\033[0m"
    exit 1
fi

# Check if frontend dependencies are installed
echo -e "\n\033[33mChecking frontend dependencies...\033[0m"
if [ ! -d "frontend/node_modules" ]; then
    echo -e "\033[33mInstalling frontend dependencies (first time only)...\033[0m"
    cd frontend
    npm install
    cd ..
    echo -e "\033[32mFrontend dependencies installed\033[0m"
else
    echo -e "\033[32mFrontend dependencies OK\033[0m"
fi

# Start backend
echo -e "\n\033[33mStarting backend server...\033[0m"
uv run worldreasoner --reload &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start frontend
echo -e "\033[33mStarting frontend dev server...\033[0m"
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# Print info
echo -e "\n\033[32m=== WorldReasoner Graph Visualization Started ===\033[0m"
echo -e "\033[36mBackend API: http://localhost:8018\033[0m"
echo -e "\033[36mAPI Docs:    http://localhost:8018/docs\033[0m"
echo -e "\033[36mFrontend:    http://localhost:3000\033[0m"
echo -e "\n\033[33mPress Ctrl+C to stop both servers\033[0m"

# Handle shutdown
trap "echo -e '\n\033[33mStopping servers...\033[0m'; kill $BACKEND_PID $FRONTEND_PID; exit" SIGINT SIGTERM

# Wait
wait
