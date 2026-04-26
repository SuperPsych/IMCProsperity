def generate_paths(initial_price, time_horizon_weeks, num_simulations=100000):
    """
    Generates Monte Carlo price paths for AETHER_CRYSTAL using Geometric Brownian Motion.
    
    Parameters:
    initial_price (float): The starting spot price (S0)
    time_horizon_weeks (int): The total weeks to simulate
    num_simulations (int): Number of paths to generate
    
    Returns:
    np.ndarray: Array of shape (total_steps + 1, num_simulations) containing the paths.
    """
    # Fixed challenge parameters
    sigma = 2.51           
    mu = 0.0               
    trading_days_yr = 252
    steps_per_day = 4
    days_per_week = 5
    
    # Calculate exact time steps
    dt = 1 / (trading_days_yr * steps_per_day)
    total_steps = time_horizon_weeks * days_per_week * steps_per_day
    
    # Generate random standard normal variables
    Z = np.random.standard_normal((total_steps, num_simulations))
    
    # Calculate the GBM drift and diffusion components
    drift = (mu - 0.5 * sigma**2) * dt
    diffusion = sigma * np.sqrt(dt) * Z
    
    # Compute step multipliers
    step_multipliers = np.exp(drift + diffusion)
    
    # Initialize the path array and apply cumulative product
    paths = np.zeros((total_steps + 1, num_simulations))
    paths[0] = initial_price
    paths[1:] = initial_price * np.cumprod(step_multipliers, axis=0)
    
    return paths

# Example usage:
paths = generate_paths(initial_price=50.0, time_horizon_weeks=3, num_simulations=100000)